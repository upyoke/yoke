"""Source-suite fixtures for workspace authority tests."""

from __future__ import annotations

import json
import os
import tempfile

import pytest

from yoke_contracts.machine_config import schema as machine_config_contract
from yoke_core.domain.work_claim_targets import make_item_target


SESSION_A = "sess-a"
SESSION_B = "sess-b"
PROJECT_REPO_ROOT = "/opt/yoke-test"
SCRATCH_ROOT = f"{PROJECT_REPO_ROOT}/.scratch-root"
RETIRED_DISPATCH_ROOT = "data/sessions/dispatch-inputs"
RUN_ID = "test-run"


@pytest.fixture
def conn():
    from runtime.api.fixtures import pg_testdb
    from runtime.api.fixtures.schema_ddl import apply_fixture_ddl

    name = pg_testdb.create_test_database()
    c = pg_testdb.drop_database_on_close(pg_testdb.connect_test_database(name), name)
    apply_fixture_ddl(
        c,
        """
        CREATE TABLE projects (
            id INTEGER PRIMARY KEY, slug TEXT UNIQUE
        );
        CREATE TABLE items (
            id INTEGER PRIMARY KEY, project_id INTEGER,
            status TEXT, workflow_id TEXT, workflow_version_id INTEGER
        );
        CREATE TABLE item_worktrees (
            id INTEGER PRIMARY KEY, item_id INTEGER NOT NULL,
            branch TEXT NOT NULL, path TEXT, lane_role TEXT NOT NULL,
            state TEXT NOT NULL DEFAULT 'active',
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
            released_at TEXT
        );
        CREATE TABLE epic_tasks (
            epic_id INTEGER NOT NULL, task_num INTEGER NOT NULL,
            item_worktree_id INTEGER, PRIMARY KEY (epic_id, task_num)
        );
        CREATE TABLE work_claims (
            id INTEGER PRIMARY KEY, session_id TEXT, target_kind TEXT,
            scope TEXT, released_at TEXT
        );
        CREATE TABLE harness_sessions (
            session_id TEXT PRIMARY KEY, current_item_id INTEGER
        );
        """,
    )
    from yoke_core.domain.workflow_registry import converge_builtin_workflows
    from yoke_core.domain.workflow_schema import ensure_workflow_schema

    ensure_workflow_schema(c)
    converge_builtin_workflows(c)
    yield c
    c.close()


@pytest.fixture
def patch_conn(conn, monkeypatch):
    from yoke_core.domain import verification_tree_binding
    from yoke_core.domain.session_claimed_worktrees import claimed_worktrees

    def _lookup(session_id: str):
        rows = claimed_worktrees(conn, session_id=session_id)
        current = conn.execute(
            "SELECT i.id, i.status FROM harness_sessions hs "
            "JOIN items i ON i.id = hs.current_item_id "
            "WHERE hs.session_id = %s LIMIT 1",
            (session_id,),
        ).fetchone()
        before_implementation = None
        if current is not None:
            from yoke_core.domain.workflow_runtime import (
                load_item_workflow_runtime,
            )

            before_implementation = load_item_workflow_runtime(
                conn,
                int(current["id"]),
            ).is_before_implementation(str(current["status"]))
        return verification_tree_binding.ClaimLookup(
            worktrees=tuple(row.worktree_path for row in rows),
            current_item_before_implementation=before_implementation,
        )

    monkeypatch.setattr(
        verification_tree_binding,
        "resolve_claim_worktrees",
        _lookup,
    )
    return conn


def _project_id(project: str = "yoke") -> int:
    return {"yoke": 1, "externalwebapp": 2}.get(project, 100)


#: Checkout most recently registered by :func:`_seed_project`, so a lane
#: seeded afterwards can record the path worktree preparation would have
#: written. Lane authority is read from ``item_worktrees.path``, so a lane
#: row without it grants nothing and quietly makes a fixture meaningless.
_REGISTERED_CHECKOUT: "str | None" = None


def _seed_project(conn, checkout: str, project: str = "yoke") -> None:
    global _REGISTERED_CHECKOUT
    _REGISTERED_CHECKOUT = str(checkout)
    conn.execute(
        "INSERT INTO projects (id, slug) VALUES (%s, %s)",
        (_project_id(project), project),
    )
    config_dir = tempfile.mkdtemp(prefix="yoke-machine-config-")
    config_path = os.path.join(config_dir, "config.json")
    payload = {
        "projects": machine_config_contract.upsert_project_entry(
            [],
            checkout=checkout,
            project_id=_project_id(project),
        )
    }
    with open(config_path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, sort_keys=True)
    os.environ["YOKE_MACHINE_CONFIG_FILE"] = config_path
    conn.commit()


def _seed_item(conn, item_id: int, branch: str | None, project: str = "yoke") -> None:
    from yoke_core.domain.workflow_registry import resolve_current_workflow_pin

    workflow_id, workflow_version_id = resolve_current_workflow_pin(conn, "issue")
    conn.execute(
        "INSERT INTO items (id, project_id, workflow_id, "
        "workflow_version_id) VALUES (%s, %s, %s, %s)",
        (
            item_id,
            _project_id(project),
            workflow_id,
            workflow_version_id,
        ),
    )
    if branch is not None:
        lane_path = (
            os.path.join(_REGISTERED_CHECKOUT, ".worktrees", branch)
            if _REGISTERED_CHECKOUT
            else None
        )
        conn.execute(
            "INSERT INTO item_worktrees "
            "(item_id, branch, path, lane_role, state, created_at, "
            "updated_at) "
            "VALUES (%s, %s, %s, 'implementation', 'active', %s, %s)",
            (
                item_id,
                branch,
                lane_path,
                "2026-01-01T00:00:00Z",
                "2026-01-01T00:00:00Z",
            ),
        )
    conn.commit()


def _seed_claim(conn, session_id: str, item_id: int) -> None:
    conn.execute(
        "INSERT INTO work_claims (session_id, target_kind, scope) "
        "VALUES (%s, 'item', %s)",
        (session_id, make_item_target(item_id).scope_json()),
    )
    conn.commit()


def _seed_session_status(conn, session_id: str, item_id: int, status: str) -> None:
    conn.execute(
        "INSERT INTO harness_sessions (session_id, current_item_id) VALUES (%s, %s)",
        (session_id, item_id),
    )
    conn.execute("UPDATE items SET status = %s WHERE id = %s", (status, item_id))
    conn.commit()
