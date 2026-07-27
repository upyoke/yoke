"""Backend-aware fixtures for path-claim guard live-DB tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db
from runtime.api.fixtures.machine_config_test import register_machine_checkout
from yoke_core.domain.schema_init_apply import execute_schema_script

_LIVE_DDL = (
    "CREATE TABLE projects(id INTEGER PRIMARY KEY,slug TEXT UNIQUE NOT NULL);"
    "CREATE TABLE items(id INTEGER PRIMARY KEY,type TEXT NOT NULL,project_id INTEGER);"
    "CREATE TABLE item_worktrees(id INTEGER PRIMARY KEY,item_id INTEGER NOT NULL,"
    "branch TEXT NOT NULL,path TEXT,lane_role TEXT NOT NULL,state TEXT NOT NULL,"
    "created_at TEXT,updated_at TEXT,released_at TEXT);"
    "CREATE TABLE harness_sessions(session_id TEXT PRIMARY KEY,current_item_id TEXT);"
    "CREATE TABLE path_claims(id INTEGER PRIMARY KEY,item_id INTEGER,integration_target TEXT,state TEXT,session_id TEXT,owner_kind TEXT,owner_item_id INTEGER,owner_session_id TEXT,owner_work_claim_id INTEGER);"
    "CREATE TABLE path_targets(id INTEGER PRIMARY KEY AUTOINCREMENT,path_string TEXT UNIQUE);"
    "CREATE TABLE path_claim_targets(id INTEGER PRIMARY KEY AUTOINCREMENT,claim_id INTEGER,target_id INTEGER);"
    "CREATE TABLE epic_dispatch_chains(id INTEGER PRIMARY KEY AUTOINCREMENT,"
    "epic_id INTEGER NOT NULL,item_worktree_id INTEGER);"
)


def _p(conn) -> str:
    from yoke_core.domain import db_backend

    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _apply_live_schema() -> None:
    from yoke_core.domain import db_backend

    conn = db_backend.connect()
    try:
        execute_schema_script(conn, _LIVE_DDL)
        from yoke_core.domain.workflow_registry import converge_builtin_workflows
        from yoke_core.domain.workflow_schema import ensure_workflow_schema

        ensure_workflow_schema(conn)
        converge_builtin_workflows(conn)
        conn.commit()
    finally:
        conn.close()


@pytest.fixture
def live_db(tmp_path):
    """Seed the backend-routed DB used by live no-conn guard tests."""
    with init_test_db(tmp_path, apply_schema=_apply_live_schema) as db_path:
        conn = connect_test_db(db_path)

        def _seed(**kw):
            p = _p(conn)
            repo_path = Path(str(kw["repo_path"]))
            register_machine_checkout(repo_path.parent, repo_path, 1)
            conn.execute(
                f"INSERT INTO projects VALUES({p},{p})",
                (1, "yoke"),
            )
            from yoke_core.domain.workflow_registry import (
                resolve_current_workflow_pin,
            )

            workflow_id = str(kw["workflow_id"])
            _, version_id = resolve_current_workflow_pin(conn, workflow_id)
            conn.execute(
                "INSERT INTO items "
                "(id,type,project_id,workflow_id,workflow_version_id) "
                f"VALUES({p},{p},{p},{p},{p})",
                (
                    kw["item_id"],
                    workflow_id,
                    1,
                    workflow_id,
                    version_id,
                ),
            )
            next_lane_id = 100
            if kw.get("items_worktree"):
                conn.execute(
                    "INSERT INTO item_worktrees "
                    "(id,item_id,branch,lane_role,state) "
                    f"VALUES({p},{p},{p},{p},{p})",
                    (
                        next_lane_id,
                        kw["item_id"],
                        kw["items_worktree"],
                        "implementation",
                        "active",
                    ),
                )
                next_lane_id += 1
            conn.execute(
                f"INSERT INTO harness_sessions VALUES({p},{p})",
                (kw["session_id"], str(kw["item_id"])),
            )
            conn.execute(
                f"INSERT INTO path_claims VALUES({p},{p},{p},{p},{p},{p},{p},{p},{p})",
                (
                    99,
                    kw["item_id"],
                    "main",
                    "active",
                    None,
                    "item",
                    kw["item_id"],
                    None,
                    None,
                ),
            )
            for path in kw["covered_paths"]:
                cur = conn.execute(
                    f"INSERT INTO path_targets(path_string) VALUES({p}) RETURNING id",
                    (path,),
                )
                conn.execute(
                    f"INSERT INTO path_claim_targets(claim_id,target_id) VALUES({p},{p})",
                    (99, int(cur.fetchone()[0])),
                )
            for branch in kw["chains"]:
                conn.execute(
                    "INSERT INTO item_worktrees "
                    "(id,item_id,branch,lane_role,state) "
                    f"VALUES({p},{p},{p},{p},{p})",
                    (
                        next_lane_id,
                        kw["item_id"],
                        branch,
                        "worker",
                        "active",
                    ),
                )
                conn.execute(
                    "INSERT INTO epic_dispatch_chains"
                    f"(epic_id,item_worktree_id) VALUES({p},{p})",
                    (kw["item_id"], next_lane_id),
                )
                next_lane_id += 1
            conn.commit()

        try:
            yield _seed
        finally:
            conn.close()
