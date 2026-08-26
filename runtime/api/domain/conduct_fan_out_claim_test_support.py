"""Shared database and filesystem helpers for conduct fan-out claim tests."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable, Tuple

import pytest

from runtime.api.fixtures import pg_testdb
from runtime.api.fixtures.machine_config_test import register_machine_checkout
from runtime.api.fixtures.schema_ddl import apply_fixture_ddl
from yoke_core.domain.work_claim_targets import make_epic_task_target


@pytest.fixture
def conn():
    name = pg_testdb.create_test_database()
    c = pg_testdb.drop_database_on_close(pg_testdb.connect_test_database(name), name)
    apply_fixture_ddl(
        c,
        """
        CREATE TABLE projects (id INTEGER PRIMARY KEY, slug TEXT UNIQUE);
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
        """,
    )
    from yoke_core.domain.workflow_registry import converge_builtin_workflows
    from yoke_core.domain.workflow_schema import ensure_workflow_schema

    ensure_workflow_schema(c)
    converge_builtin_workflows(c)
    yield c
    c.close()


def acquire_claim(conn, *, session_id, epic_id, task_num) -> int:
    cur = conn.execute(
        "INSERT INTO work_claims (session_id, target_kind, scope) "
        "VALUES (%s, 'epic_task', %s) RETURNING id",
        (session_id, make_epic_task_target(epic_id, task_num).scope_json()),
    )
    claim_id = int(cur.fetchone()[0])
    conn.commit()
    return claim_id


def release_claim(conn, claim_id, *, when="2026-05-27T13:00:00Z") -> None:
    conn.execute(
        "UPDATE work_claims SET released_at = %s WHERE id = %s",
        (when, claim_id),
    )
    conn.commit()


def ensure_item_worktree(
    conn,
    *,
    item_id: int,
    branch: str,
    lane_role: str,
    repo: Path,
) -> int:
    """Return the lane's id, creating it with its recorded path.

    ``repo`` is required because lane authority is read from
    ``item_worktrees.path``: a lane row without it authorises nothing, so
    a fixture that omits it looks meaningful while proving nothing.
    """
    row = conn.execute(
        "SELECT id FROM item_worktrees "
        "WHERE item_id = %s AND branch = %s AND state = 'active'",
        (item_id, branch),
    ).fetchone()
    if row is not None:
        return int(row["id"])
    row = conn.execute(
        "INSERT INTO item_worktrees "
        "(item_id, branch, path, lane_role, state, created_at, updated_at) "
        "VALUES (%s, %s, %s, %s, 'active', %s, %s) RETURNING id",
        (
            item_id,
            branch,
            str(Path(repo) / ".worktrees" / branch),
            lane_role,
            "2026-01-01T00:00:00Z",
            "2026-01-01T00:00:00Z",
        ),
    ).fetchone()
    return int(row["id"])


def seed_fanout(
    conn,
    repo: Path,
    *,
    item_id: int,
    session_id: str,
    lanes: Iterable[Tuple[int, str]],
) -> dict:
    """Materialise an epic and claim each supplied task worktree."""
    conn.execute(
        "INSERT INTO projects (id, slug) VALUES (1, 'yoke')",
    )
    register_machine_checkout(repo.parent / "machine-config", repo, 1)
    from yoke_core.domain.workflow_registry import resolve_current_workflow_pin

    workflow_id, workflow_version_id = resolve_current_workflow_pin(conn, "epic")
    conn.execute(
        "INSERT INTO items (id, project_id, status, workflow_id, "
        "workflow_version_id) VALUES (%s, 1, 'implementing', %s, %s)",
        (item_id, workflow_id, workflow_version_id),
    )
    claims: dict = {}
    for task_num, branch in lanes:
        lane_id = ensure_item_worktree(
            conn,
            item_id=item_id,
            branch=branch,
            lane_role="worker",
            repo=repo,
        )
        conn.execute(
            "INSERT INTO epic_tasks (epic_id, task_num, item_worktree_id) "
            "VALUES (%s, %s, %s)",
            (item_id, task_num, lane_id),
        )
        (repo / ".worktrees" / branch).mkdir(parents=True, exist_ok=True)
        claims[task_num] = acquire_claim(
            conn,
            session_id=session_id,
            epic_id=item_id,
            task_num=task_num,
        )
    return claims


def write_target(repo: Path, branch: str, name: str = "x.py") -> Path:
    target = repo / ".worktrees" / branch / "src" / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("# stub")
    return target
