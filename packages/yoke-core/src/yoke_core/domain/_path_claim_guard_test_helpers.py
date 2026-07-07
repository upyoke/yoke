"""Backend-aware fixtures for path-claim guard live-DB tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db
from runtime.api.fixtures.machine_config_test import register_machine_checkout
from yoke_core.domain.schema_init_apply import execute_schema_script

_LIVE_DDL = (
    "CREATE TABLE projects(id INTEGER PRIMARY KEY,slug TEXT UNIQUE NOT NULL);"
    "CREATE TABLE items(id INTEGER PRIMARY KEY,type TEXT NOT NULL,worktree TEXT,project_id INTEGER);"
    "CREATE TABLE harness_sessions(session_id TEXT PRIMARY KEY,current_item_id TEXT);"
    "CREATE TABLE path_claims(id INTEGER PRIMARY KEY,item_id INTEGER,integration_target TEXT,state TEXT,session_id TEXT,owner_kind TEXT,owner_item_id INTEGER,owner_session_id TEXT,owner_work_claim_id INTEGER);"
    "CREATE TABLE path_targets(id INTEGER PRIMARY KEY AUTOINCREMENT,path_string TEXT UNIQUE);"
    "CREATE TABLE path_claim_targets(id INTEGER PRIMARY KEY AUTOINCREMENT,claim_id INTEGER,target_id INTEGER);"
    "CREATE TABLE epic_dispatch_chains(id INTEGER PRIMARY KEY AUTOINCREMENT,epic_id INTEGER NOT NULL,worktree TEXT NOT NULL,worktree_path TEXT);"
)


def _p(conn) -> str:
    from yoke_core.domain import db_backend

    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _apply_live_schema() -> None:
    from yoke_core.domain import db_backend

    conn = db_backend.connect()
    try:
        execute_schema_script(conn, _LIVE_DDL)
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
            conn.execute(
                f"INSERT INTO items VALUES({p},{p},{p},{p})",
                (
                    kw["item_id"],
                    kw["item_type"],
                    kw.get("items_worktree") or None,
                    1,
                ),
            )
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
                    f"INSERT INTO epic_dispatch_chains(epic_id,worktree) VALUES({p},{p})",
                    (kw["item_id"], branch),
                )
            conn.commit()

        try:
            yield _seed
        finally:
            conn.close()
