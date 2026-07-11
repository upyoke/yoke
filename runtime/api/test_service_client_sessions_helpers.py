"""Shared fixture and helpers for the test_service_client_sessions[_*] family."""

from __future__ import annotations

import os

import pytest

from runtime.api.fixtures.file_test_db import init_test_db
from runtime.api.sessions_api_stale_test_helpers import apply_ddl_statements
from runtime.api.test_dependency_schema import (
    ITEMS_SCHEMA,
    ITEM_DEPENDENCIES_SCHEMA,
    PROJECTS_SCHEMA,
)
from runtime.api.test_service_client import _run_client
from runtime.api.test_constants import TEST_MODEL_ID

# Session/claim/event/actor tables the session-offer surface reads. ``actors``
# is required on Postgres: register_session's validate_actor_id probe queries it
# (the facade re-raises a missing relation as no-such-table). INTEGER PRIMARY KEY
# and inline FK clauses are translated/stripped by the facade so the same DDL
# applies on both backends through backend-routed statement execution.
_SESSION_OFFER_SCHEMA_DDL = """
    CREATE TABLE harness_sessions (
        session_id TEXT PRIMARY KEY,
        executor TEXT NOT NULL,
        executor_display_name TEXT DEFAULT NULL,
        provider TEXT NOT NULL,
        model TEXT NOT NULL,
        execution_lane TEXT NOT NULL DEFAULT 'DARIUS',
        capabilities TEXT,
        workspace TEXT,
        project_id INTEGER NOT NULL DEFAULT 1 REFERENCES projects(id),
        mode TEXT NOT NULL DEFAULT 'wait',
        offered_at TEXT NOT NULL,
        last_heartbeat TEXT NOT NULL,
        ended_at TEXT,
        offer_envelope TEXT,
        current_item_id TEXT DEFAULT NULL,
        current_item_set_at TEXT DEFAULT NULL,
        recent_item_id TEXT DEFAULT NULL,
        recent_item_status TEXT DEFAULT NULL,
        recent_item_recorded_at TEXT DEFAULT NULL,
        actor_id INTEGER DEFAULT NULL,
        last_tool_call_at TEXT DEFAULT NULL,
        tool_call_count INTEGER NOT NULL DEFAULT 0,
        episode_started_at TEXT DEFAULT NULL,
        pending_resume_notice TEXT DEFAULT NULL,
        last_chain_step INTEGER DEFAULT NULL,
        last_checkpoint_at TEXT DEFAULT NULL
    );

    CREATE TABLE work_claims (
    id INTEGER PRIMARY KEY,
    session_id TEXT NOT NULL,
    target_kind TEXT NOT NULL CHECK(target_kind IN ('item','epic_task','process')),
    item_id INTEGER,
    epic_id INTEGER,
    task_num INTEGER,
    process_key TEXT,
    conflict_group TEXT,
    claim_type TEXT NOT NULL DEFAULT 'exclusive' CHECK(claim_type='exclusive'),
    claimed_at TEXT NOT NULL,
    last_heartbeat TEXT NOT NULL,
    released_at TEXT,
    release_reason TEXT CHECK(release_reason IS NULL OR release_reason IN ('completed','released','reclaimed','handed_off','expired','session_ended')),
    reason TEXT DEFAULT NULL,
    reason_intent TEXT DEFAULT NULL,
    release_reason_intent TEXT DEFAULT NULL,
    CHECK (
      (target_kind='item' AND item_id IS NOT NULL AND epic_id IS NULL AND task_num IS NULL AND process_key IS NULL AND conflict_group IS NULL) OR
      (target_kind='epic_task' AND item_id IS NULL AND epic_id IS NOT NULL AND task_num IS NOT NULL AND process_key IS NULL AND conflict_group IS NULL) OR
      (target_kind='process' AND item_id IS NULL AND epic_id IS NULL AND task_num IS NULL AND process_key IS NOT NULL AND conflict_group IS NOT NULL)
    ),
    FOREIGN KEY (session_id) REFERENCES harness_sessions(session_id)
);

    CREATE TABLE IF NOT EXISTS path_claims (
        id INTEGER PRIMARY KEY,
        work_claim_id INTEGER,
        state TEXT,
        released_at TEXT,
        cancelled_at TEXT,
        release_reason TEXT
    );

    CREATE TABLE IF NOT EXISTS events (
        id INTEGER PRIMARY KEY,
        event_id TEXT UNIQUE,
        event_name TEXT NOT NULL,
        event_kind TEXT,
        event_type TEXT,
        source_type TEXT,
        session_id TEXT,
        severity TEXT DEFAULT 'INFO',
        event_outcome TEXT,
        org_id TEXT,
        environment TEXT,
        service TEXT,
        project_id INTEGER DEFAULT 1 REFERENCES projects(id),
        actor_id INTEGER,
        item_id TEXT,
        task_num INTEGER,
        agent TEXT,
        tool_name TEXT,
        duration_ms INTEGER,
        exit_code INTEGER,
        trace_id TEXT,
        parent_id TEXT,
        anomaly_flags TEXT,
        tool_use_id TEXT,
        turn_id TEXT,
        hook_event_name TEXT,
        envelope TEXT,
        created_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS actors (
        id INTEGER PRIMARY KEY,
        kind TEXT NOT NULL CHECK(kind IN ('human','system')),
        system_component TEXT,
        created_at TEXT NOT NULL,
        CHECK (
            (kind = 'system' AND system_component IS NOT NULL)
            OR
            (kind = 'human' AND system_component IS NULL)
        )
    );
"""


def _apply_session_offer_schema() -> None:
    """``init_test_db`` ``apply_schema`` strategy for the session-offer family.

    Builds the items / dependencies / session / claim / event / actor schema and
    seeds the three canonical items on the backend-resolved test DB (``YOKE_DB``
    on SQLite, the repointed per-test ``YOKE_PG_DSN`` on Postgres). Resolves its
    own connection through the backend factory, satisfying the zero-arg contract.
    """
    from yoke_core.domain import db_backend

    conn = db_backend.connect()
    try:
        apply_ddl_statements(
            conn, PROJECTS_SCHEMA, ITEMS_SCHEMA, ITEM_DEPENDENCIES_SCHEMA,
            _SESSION_OFFER_SCHEMA_DDL,
        )

        # Seed items: one runnable, one done, one blocked
        conn.execute(
            """INSERT INTO items
               (id, title, type, status, priority, project_id, project_sequence,
                created_at, updated_at, source, frozen)
               VALUES (10, 'Runnable task', 'issue', 'refined-idea', 'high', 1, 10,
                       '2026-03-01', '2026-03-01', 'user', 0)"""
        )
        conn.execute(
            """INSERT INTO items
               (id, title, type, status, priority, project_id, project_sequence,
                created_at, updated_at, source, frozen)
               VALUES (11, 'Done task', 'issue', 'done', 'medium', 1, 11,
                       '2026-03-01', '2026-03-01', 'user', 0)"""
        )
        conn.execute(
            """INSERT INTO items
               (id, title, type, status, priority, project_id, project_sequence,
                created_at, updated_at, source, frozen)
               VALUES (12, 'Blocked task', 'issue', 'idea', 'low', 1, 12,
                       '2026-03-01', '2026-03-01', 'user', 0)"""
        )
        conn.execute(
            """INSERT INTO item_dependencies
               (dependent_item, blocking_item, gate_point, satisfaction, source, rationale, created_at)
               VALUES ('YOK-12', 'YOK-10', 'activation', 'status:done', 'shepherd', 'Task 12 depends on task 10', '2026-04-20T00:00:00Z')"""
        )
        conn.commit()
    finally:
        conn.close()


@pytest.fixture()
def session_offer_db(tmp_path):
    """Backend-aware DB with session tables and items for session-offer tests.

    ``tmp_path`` doubles as the workspace: the per-test DB lives at
    ``tmp_path/yoke.db`` (an ignored placeholder on Postgres — the connection
    target is the repointed DSN), the SML ``strategy/`` dir and any adjacent
    ``config`` file the offer path reads live under the same root.
    """
    with init_test_db(tmp_path, apply_schema=_apply_session_offer_schema) as db_path:
        # Create SML files so scheduler sees SML as coherent
        strategy_dir = os.path.join(str(tmp_path), "strategy")
        os.makedirs(strategy_dir, exist_ok=True)
        for sml_file in ("MISSION.md", "LANDSCAPE.md", "VISION.md", "MASTER-PLAN.md"):
            with open(os.path.join(strategy_dir, sml_file), "w") as f:
                f.write(f"# {sml_file}\n")

        yield {"db_path": db_path, "tmp_dir": str(tmp_path)}


def _pre_register_session(db_path: str, session_id: str, executor: str = "DARIUS",
                          provider: str = "anthropic", model: str = TEST_MODEL_ID,
                          workspace: str = "/tmp", lane: str = "primary"):
    """Pre-register a session in the DB so session-offer can find it.

    Uses session-begin which is idempotent — safe to call multiple times.
    """
    r = _run_client([
        "session-begin",
        "--session-id", session_id,
        "--executor", executor,
        "--provider", provider,
        "--model", model,
        "--workspace", workspace,
        "--project-id", "1",
    ], db_path=db_path)
    assert r.returncode == 0, f"session-begin failed: {r.stderr}"
    return r
