"""Shared fixtures for planning-phase path-claim guard tests."""

from __future__ import annotations

import pytest

from yoke_core.domain import project_scratch_dir as scratch
from yoke_core.domain.schema_init_apply import execute_schema_script
from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db


PROJECT_REPO_ROOT = "/opt/yoke-test"
SCRATCH_ROOT = f"{PROJECT_REPO_ROOT}/.scratch-root"
RETIRED_DISPATCH_ROOT = "data/sessions/dispatch-inputs"
RUN_ID = "test-run"


def _configure_scratch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(scratch.ENV_KEY, SCRATCH_ROOT)
    monkeypatch.setenv("YOKE_RUN_ID", RUN_ID)
    monkeypatch.delenv("YOKE_PROJECT", raising=False)
    monkeypatch.setattr(scratch, "_ensure_writable_dir", lambda path: True)


def _dispatch_target(
    *,
    item_id: int = 1844,
    dispatch_session: str = "x",
    attempt: int = 1,
    filename: str = "s.md",
) -> str:
    return str(
        scratch.dispatch_inputs_dir(
            item_id=item_id,
            session_id=dispatch_session,
            attempt=attempt,
            create=False,
        )
        / filename
    )


def _apply_widener_schema() -> None:
    from yoke_core.domain import db_backend

    conn = db_backend.connect()
    try:
        execute_schema_script(
            conn,
            "CREATE TABLE IF NOT EXISTS items(id INTEGER PRIMARY KEY,"
            " type TEXT NOT NULL, status TEXT NOT NULL,"
            " worktree TEXT, project_id INTEGER, project_sequence INTEGER);"
            "CREATE TABLE IF NOT EXISTS harness_sessions("
            " session_id TEXT PRIMARY KEY, current_item_id INTEGER);"
        )
        conn.commit()
    finally:
        conn.close()


def _placeholder(conn) -> str:
    from yoke_core.domain import db_backend

    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _seed(conn, *, session_id, item_id, status, item_type="issue"):
    p = _placeholder(conn)
    conn.execute(
        "INSERT INTO items(id,type,status,worktree,project_id,project_sequence)"
        f" VALUES ({p},{p},{p},NULL,1,{p}) "
        "ON CONFLICT (id) DO UPDATE SET "
        "type=excluded.type, status=excluded.status, "
        "worktree=excluded.worktree, project_id=excluded.project_id, "
        "project_sequence=excluded.project_sequence",
        (item_id, item_type, status, item_id),
    )
    conn.execute(
        "INSERT INTO harness_sessions(session_id,current_item_id)"
        f" VALUES ({p},{p}) "
        "ON CONFLICT (session_id) DO UPDATE SET "
        "current_item_id=excluded.current_item_id",
        (session_id, item_id),
    )
    conn.commit()


@pytest.fixture
def widener_db(tmp_path, monkeypatch):
    with init_test_db(tmp_path, apply_schema=_apply_widener_schema) as db_path:
        conn = connect_test_db(db_path)
        try:
            _configure_scratch(monkeypatch)
            monkeypatch.delenv("YOKE_SESSION_ID", raising=False)
            yield conn
        finally:
            conn.close()
