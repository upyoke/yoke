"""Shared fixtures for planning-phase path-claim guard tests."""

from __future__ import annotations

import pytest

from yoke_core.domain import project_scratch_dir as scratch
from yoke_core.domain.schema_init_apply import execute_schema_script


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
            " workflow_id TEXT NOT NULL,"
            " workflow_version_id INTEGER NOT NULL,"
            " status TEXT NOT NULL,"
            " project_id INTEGER, project_sequence INTEGER);"
            "CREATE TABLE IF NOT EXISTS item_worktrees("
            " id INTEGER PRIMARY KEY, item_id INTEGER NOT NULL,"
            " branch TEXT NOT NULL, path TEXT, lane_role TEXT NOT NULL,"
            " state TEXT NOT NULL DEFAULT 'active',"
            " created_at TEXT NOT NULL, updated_at TEXT NOT NULL,"
            " released_at TEXT);"
            "CREATE TABLE IF NOT EXISTS workflow_versions("
            " id INTEGER PRIMARY KEY, workflow_id TEXT NOT NULL,"
            " version INTEGER NOT NULL, definition_json TEXT NOT NULL,"
            " definition_digest TEXT NOT NULL);"
            "CREATE TABLE IF NOT EXISTS harness_sessions("
            " session_id TEXT PRIMARY KEY, current_item_id INTEGER);"
        )
        conn.commit()
    finally:
        conn.close()


def _placeholder(conn) -> str:
    from yoke_core.domain import db_backend

    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _seed(
    conn,
    *,
    session_id,
    item_id,
    status,
    workflow_id="issue",
):
    from yoke_core.domain.builtin_workflow_definitions import (
        builtin_workflow_definition,
    )
    from yoke_core.domain.workflow_registry import (
        canonical_definition_json,
        definition_digest,
    )

    p = _placeholder(conn)
    fixture = builtin_workflow_definition(workflow_id)
    definition = fixture["definition"]
    workflow_version_id = {
        "issue": 1,
        "epic": 2,
        "blitz": 3,
        "dash": 4,
    }[workflow_id]
    conn.execute(
        "INSERT INTO workflow_versions("
        "id,workflow_id,version,definition_json,definition_digest)"
        f" VALUES ({p},{p},{p},{p},{p}) "
        "ON CONFLICT (id) DO NOTHING",
        (
            workflow_version_id,
            workflow_id,
            int(fixture["canon_version"]),
            canonical_definition_json(definition),
            definition_digest(definition),
        ),
    )
    conn.execute(
        "INSERT INTO items("
        "id,workflow_id,workflow_version_id,status,"
        "project_id,project_sequence)"
        f" VALUES ({p},{p},{p},{p},1,{p}) "
        "ON CONFLICT (id) DO UPDATE SET "
        "workflow_id=excluded.workflow_id, "
        "workflow_version_id=excluded.workflow_version_id, "
        "status=excluded.status, "
        "project_id=excluded.project_id, "
        "project_sequence=excluded.project_sequence",
        (
            item_id,
            workflow_id,
            workflow_version_id,
            status,
            item_id,
        ),
    )
    conn.execute(
        "INSERT INTO harness_sessions(session_id,current_item_id)"
        f" VALUES ({p},{p}) "
        "ON CONFLICT (session_id) DO UPDATE SET "
        "current_item_id=excluded.current_item_id",
        (session_id, item_id),
    )
    conn.commit()
