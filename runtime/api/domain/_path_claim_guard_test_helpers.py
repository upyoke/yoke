"""Source-suite fixtures for path-claim guard live-DB tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db
from runtime.api.fixtures.machine_config_test import register_machine_checkout
from yoke_core.domain.schema_init_apply import execute_schema_script
from yoke_core.domain.work_claim_targets import (
    make_epic_task_target,
    make_item_target,
)

_LIVE_DDL = (
    "CREATE TABLE projects(id INTEGER PRIMARY KEY,slug TEXT UNIQUE NOT NULL);"
    "CREATE TABLE items(id INTEGER PRIMARY KEY,status TEXT NOT NULL,project_id INTEGER);"
    "CREATE TABLE item_worktrees(id INTEGER PRIMARY KEY,item_id INTEGER NOT NULL,"
    "branch TEXT NOT NULL,path TEXT,lane_role TEXT NOT NULL,state TEXT NOT NULL,"
    "created_at TEXT,updated_at TEXT,released_at TEXT);"
    "CREATE TABLE harness_sessions(session_id TEXT PRIMARY KEY,current_item_id TEXT);"
    "CREATE TABLE path_claims(id INTEGER PRIMARY KEY,integration_target TEXT,state TEXT,mode TEXT DEFAULT 'exclusive',owner_kind TEXT,owner_item_id INTEGER,owner_session_id TEXT,owner_work_claim_id INTEGER,registered_by_actor_id INTEGER,registered_by_session_id TEXT);"
    "CREATE TABLE path_targets(id INTEGER PRIMARY KEY AUTOINCREMENT,path_string TEXT UNIQUE,kind TEXT NOT NULL DEFAULT 'directory');"
    "CREATE TABLE path_claim_targets(id INTEGER PRIMARY KEY AUTOINCREMENT,claim_id INTEGER,target_id INTEGER);"
    "CREATE TABLE path_claim_task_bindings(claim_id INTEGER NOT NULL,"
    "epic_id INTEGER NOT NULL,task_num INTEGER NOT NULL,bound_at TEXT NOT NULL,"
    "PRIMARY KEY(claim_id,epic_id,task_num));"
    "CREATE TABLE epic_tasks(id INTEGER PRIMARY KEY AUTOINCREMENT,"
    "epic_id INTEGER NOT NULL,task_num INTEGER NOT NULL,status TEXT,"
    "item_worktree_id INTEGER,UNIQUE(epic_id,task_num));"
    "CREATE TABLE epic_task_files(id INTEGER PRIMARY KEY AUTOINCREMENT,"
    "epic_id INTEGER NOT NULL,task_num INTEGER NOT NULL,file_path TEXT NOT NULL,"
    "UNIQUE(epic_id,task_num,file_path));"
    "CREATE TABLE work_claims(id INTEGER PRIMARY KEY AUTOINCREMENT,"
    "session_id TEXT NOT NULL,target_kind TEXT NOT NULL,scope TEXT NOT NULL,"
    "released_at TEXT,claimed_at TEXT,"
    "last_heartbeat TEXT);"
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
                "(id,status,project_id,workflow_id,workflow_version_id) "
                f"VALUES({p},{p},{p},{p},{p})",
                (
                    kw["item_id"],
                    str(kw.get("status", "implementing")),
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
                "INSERT INTO path_claims "
                "(id,integration_target,state,owner_kind,owner_item_id,"
                "owner_session_id,owner_work_claim_id,registered_by_actor_id,"
                "registered_by_session_id) "
                f"VALUES({p},{p},{p},{p},{p},{p},{p},{p},{p})",
                (
                    99,
                    "main",
                    "active",
                    "item",
                    kw["item_id"],
                    None,
                    None,
                    1,
                    kw["session_id"],
                ),
            )
            for path in kw["covered_paths"]:
                cur = conn.execute(
                    "INSERT INTO path_targets(path_string,kind) "
                    f"VALUES({p},'directory') RETURNING id",
                    (path,),
                )
                conn.execute(
                    f"INSERT INTO path_claim_targets(claim_id,target_id) VALUES({p},{p})",
                    (99, int(cur.fetchone()[0])),
                )
            for index, branch in enumerate(kw["chains"]):
                lane_id = next_lane_id
                conn.execute(
                    "INSERT INTO item_worktrees "
                    "(id,item_id,branch,lane_role,state) "
                    f"VALUES({p},{p},{p},{p},{p})",
                    (
                        lane_id,
                        kw["item_id"],
                        branch,
                        "worker",
                        "active",
                    ),
                )
                conn.execute(
                    "INSERT INTO epic_dispatch_chains"
                    f"(epic_id,item_worktree_id) VALUES({p},{p})",
                    (kw["item_id"], lane_id),
                )
                task_num = index + 1
                conn.execute(
                    "INSERT INTO epic_tasks"
                    "(epic_id,task_num,status,item_worktree_id) "
                    f"VALUES({p},{p},'implementing',{p})",
                    (kw["item_id"], task_num, lane_id),
                )
                budget_root = str(kw["covered_paths"][0]).rstrip("/")
                budget_path = f"{budget_root}/{chr(ord('a') + index)}.py"
                conn.execute(
                    "INSERT INTO epic_task_files"
                    f"(epic_id,task_num,file_path) VALUES({p},{p},{p})",
                    (kw["item_id"], task_num, budget_path),
                )
                conn.execute(
                    "INSERT INTO path_claim_task_bindings"
                    f"(claim_id,epic_id,task_num,bound_at) VALUES(99,{p},{p},{p})",
                    (
                        kw["item_id"],
                        task_num,
                        "2026-07-28T00:00:00Z",
                    ),
                )
                conn.execute(
                    "INSERT INTO work_claims"
                    "(session_id,target_kind,scope,"
                    "claimed_at,last_heartbeat) "
                    f"VALUES({p},'epic_task',{p},{p},{p})",
                    (
                        kw["session_id"],
                        make_epic_task_target(kw["item_id"], task_num).scope_json(),
                        "2026-07-28T00:00:00Z",
                        "2026-07-28T00:00:00Z",
                    ),
                )
                next_lane_id += 1
            conn.execute(
                "INSERT INTO work_claims"
                "(session_id,target_kind,scope,claimed_at,last_heartbeat) "
                f"VALUES({p},'item',{p},{p},{p})",
                (
                    kw["session_id"],
                    make_item_target(kw["item_id"]).scope_json(),
                    "2026-07-28T00:00:00Z",
                    "2026-07-28T00:00:00Z",
                ),
            )
            conn.commit()

        try:
            yield _seed
        finally:
            conn.close()
