"""Shared fixtures for workspace authority tests."""

from __future__ import annotations

import json
import os
import tempfile

import pytest

from yoke_contracts.machine_config import schema as machine_config_contract


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
    c = pg_testdb.drop_database_on_close(
        pg_testdb.connect_test_database(name), name
    )
    apply_fixture_ddl(
        c,
        """
        CREATE TABLE projects (
            id INTEGER PRIMARY KEY, slug TEXT UNIQUE
        );
        CREATE TABLE items (
            id INTEGER PRIMARY KEY, worktree TEXT, project_id INTEGER, status TEXT
        );
        CREATE TABLE epic_tasks (
            epic_id INTEGER NOT NULL, task_num INTEGER NOT NULL,
            worktree TEXT, PRIMARY KEY (epic_id, task_num)
        );
        CREATE TABLE work_claims (
            id INTEGER PRIMARY KEY, session_id TEXT, target_kind TEXT,
            item_id INTEGER, epic_id INTEGER, task_num INTEGER,
            process_key TEXT, released_at TEXT
        );
        CREATE TABLE harness_sessions (
            session_id TEXT PRIMARY KEY, current_item_id INTEGER
        );
        """
    )
    yield c
    c.close()


@pytest.fixture
def patch_conn(conn, monkeypatch):
    from yoke_core.domain import db_helpers

    class _Wrapper:
        def __enter__(self): return conn
        def __exit__(self, *exc): return False

    monkeypatch.setattr(db_helpers, "connect", lambda *a, **k: _Wrapper())
    return conn


def _project_id(project: str = "yoke") -> int:
    return {"yoke": 1, "buzz": 2}.get(project, 100)


def _seed_project(conn, checkout: str, project: str = "yoke") -> None:
    conn.execute(
        "INSERT INTO projects (id, slug) VALUES (%s, %s)",
        (_project_id(project), project),
    )
    config_dir = tempfile.mkdtemp(prefix="yoke-machine-config-")
    config_path = os.path.join(config_dir, "config.json")
    payload = {
        "projects": machine_config_contract.canonical_project_map(
            {},
            checkout=checkout,
            entry={"project_id": _project_id(project)},
        )
    }
    with open(config_path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, sort_keys=True)
    os.environ["YOKE_MACHINE_CONFIG_FILE"] = config_path
    conn.commit()


def _seed_item(conn, item_id: int, branch: str | None, project: str = "yoke") -> None:
    conn.execute(
        "INSERT INTO items (id, worktree, project_id) VALUES (%s, %s, %s)",
        (item_id, branch, _project_id(project)),
    )
    conn.commit()


def _seed_claim(conn, session_id: str, item_id: int) -> None:
    conn.execute(
        "INSERT INTO work_claims (session_id, target_kind, item_id) "
        "VALUES (%s, 'item', %s)",
        (session_id, item_id),
    )
    conn.commit()


def _seed_session_status(conn, session_id: str, item_id: int, status: str) -> None:
    conn.execute(
        "INSERT INTO harness_sessions (session_id, current_item_id) VALUES (%s, %s)",
        (session_id, item_id),
    )
    conn.execute("UPDATE items SET status = %s WHERE id = %s", (status, item_id))
    conn.commit()
