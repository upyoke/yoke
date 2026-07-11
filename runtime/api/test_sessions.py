"""Tests for yoke_core.domain.sessions -- session tracking and work claims.

Covers the five canonical claim lifecycle operations (claim, heartbeat,
release, reclaim, handoff), session registration, stale detection, and
query surface.  Uses an in-memory SQLite DB for isolation.

This is the shared-helpers parent module. Test classes live in:
  - test_sessions_lifecycle.py  (register, heartbeat, claim, release, handoff, chain, guards)
  - test_sessions_queries.py    (list, get, query surface, offer/ownership)
  - test_sessions_api.py        (CLI dispatch, events, stale reclaim, telemetry)

The shared ``conn`` fixture now builds the session schema on the disposable
Postgres authority seam; tests that still need raw SQLite use local pure-unit
doubles explicitly.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from runtime.api.test_constants import TEST_MODEL_ID

# Ensure the repo root is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from unittest.mock import patch

from runtime.api.test_dependency_schema import (
    ITEMS_SCHEMA,
    ITEM_DEPENDENCIES_SCHEMA,
    PROJECTS_SCHEMA,
)
from yoke_core.domain import db_backend
from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db
from runtime.api.sessions_api_stale_test_helpers import apply_ddl_statements
from yoke_core.domain.sessions import (
    DEFAULT_STALE_THRESHOLD_MINUTES,
    EVENT_CHAIN_STEP_COMPLETED,
    EVENT_OPERATOR_CLAIM_OVERRIDE,
    EVENT_HARNESS_SESSION_END_RELEASED_CLAIMS,
    EVENT_HARNESS_SESSION_ENDED,
    EVENT_HARNESS_SESSION_STARTED,
    EVENT_HARNESS_SESSION_STALE_SWEEP_COMPLETED,
    EVENT_WORK_CLAIMED,
    EVENT_WORK_HANDED_OFF,
    EVENT_WORK_RECLAIMED,
    EVENT_WORK_RELEASED,
    SessionError,
    claim_work,
    clean_stale_harness_sessions,
    emit_post_decision_telemetry,
    emit_next_action_chosen,
    end_session,
    end_session_if_empty,
    find_stale_sessions,
    get_claim_for_work_unit,
    handoff_claim,
    heartbeat,
    list_harness_sessions,
    list_claims_for_session,
    operator_override_release_claim,
    read_chain_checkpoint,
    reclaim_stale_session,
    reclaim_stale_item_claims,
    register_session,
    release_all_claims,
    release_claim,
    release_claims_for_done_item,
    session_offer_with_ownership,
    set_session_mode,
    update_chain_checkpoint,
    _emit_session_event,
)
from yoke_core.domain.schema_init_work_claim_indexes import (
    create_work_claim_active_uniques,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]


def _p(conn) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


from runtime.api.sessions_schema_test_ddl import _SESSIONS_AND_CLAIMS_DDL


def _create_schema(conn) -> None:
    """Create the harness_sessions, work_claims, actor, and items tables for testing.

    ``items`` is the empty best-effort target of ``read_item_status`` on the
    release-diagnose path; under the backend-aware conn on Postgres a missing
    ``items`` would raise an uncaught ``UndefinedTable`` (the caller's except is
    SQLite-pinned), so the empty table must exist for the read to return ``None``.
    """
    apply_ddl_statements(
        conn,
        PROJECTS_SCHEMA,
        ITEMS_SCHEMA,
        """
        CREATE TABLE IF NOT EXISTS actors (
            id INTEGER PRIMARY KEY,
            kind TEXT NOT NULL CHECK(kind IN ('human','system')),
            system_component TEXT,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS actor_labels (
            id INTEGER PRIMARY KEY,
            actor_id INTEGER NOT NULL,
            surface TEXT NOT NULL,
            label TEXT NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE(surface, label),
            UNIQUE(actor_id, surface)
        );
        """,
        _SESSIONS_AND_CLAIMS_DDL,
    )
    create_work_claim_active_uniques(conn)



def _apply_on_backend(build) -> None:
    """``init_test_db`` applier: run ``build(conn)`` against the backend conn."""
    c = db_backend.connect()
    try:
        build(c)
        c.commit()
    finally:
        c.close()


def _connect_with_backend_setup(tmp_path):
    """Connect to the per-test DB; enable SQLite FKs when needed."""
    c = connect_test_db(str(tmp_path / "yoke.db"))
    if not db_backend.is_postgres():
        c.execute("PRAGMA foreign_keys = ON")
    return c


@pytest.fixture
def conn(tmp_path):
    """Backend-aware connection with the session schema; per-test DB on both engines.

    The stale/reclaim paths derive SQL dialect from the backend factory and
    re-raise constraint hits as ``SessionError`` only when the conn's error type
    matches the backend, so a raw in-memory SQLite conn under the Postgres
    default uses the wrong dialect; :func:`init_test_db` keeps the engine
    matched on both.
    """
    with init_test_db(tmp_path, apply_schema=lambda: _apply_on_backend(_create_schema)):
        c = _connect_with_backend_setup(tmp_path)
        try:
            yield c
        finally:
            c.close()


def _register(conn, session_id="sess-1", **kwargs):
    """Helper to register a session with defaults."""
    defaults = dict(
        executor="DARIUS",
        provider="anthropic",
        model=TEST_MODEL_ID,
        workspace="/tmp/work",
        project_id=1,
        execution_lane="primary",
        mode="wait",
    )
    defaults.update(kwargs)
    return register_session(conn, session_id=session_id, **defaults)


# ---------------------------------------------------------------------------
# Ownership schema helpers (shared by queries and API tests)
# ---------------------------------------------------------------------------


def _create_ownership_schema(conn) -> None:
    """Create all tables needed by session_offer_with_ownership."""
    apply_ddl_statements(
        conn,
        PROJECTS_SCHEMA,
        ITEMS_SCHEMA,
        ITEM_DEPENDENCIES_SCHEMA,
        _SESSIONS_AND_CLAIMS_DDL,
    )
    create_work_claim_active_uniques(conn)


# The empty actors/events/event_registry tables the ownership-reclaim path reads
# but ``_create_ownership_schema`` does not build. Absent on SQLite these reads
# fail open; on Postgres the missing relation poisons the transaction, so they
# must exist. Columns mirror the native event emitter's INSERT so the reclaim
# emit path writes cleanly on both engines.
EMIT_PATH_TABLES = """
    CREATE TABLE IF NOT EXISTS actors (
        id INTEGER PRIMARY KEY, kind TEXT NOT NULL DEFAULT 'system',
        system_component TEXT, created_at TEXT
    );
    CREATE TABLE IF NOT EXISTS events (
        id INTEGER PRIMARY KEY, event_id TEXT UNIQUE, event_name TEXT NOT NULL,
        event_kind TEXT, event_type TEXT NOT NULL DEFAULT 'system',
        source_type TEXT, session_id TEXT, severity TEXT DEFAULT 'INFO',
        event_outcome TEXT, org_id TEXT, environment TEXT,
        service TEXT, project_id INTEGER DEFAULT 1, item_id TEXT,
        task_num INTEGER, agent TEXT, tool_name TEXT, duration_ms INTEGER,
        trace_id TEXT, parent_id TEXT, anomaly_flags TEXT, tool_use_id TEXT,
        turn_id TEXT, hook_event_name TEXT, envelope TEXT,
        created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS event_registry (
        event_name TEXT PRIMARY KEY, owner_service TEXT, status TEXT
    );
"""


def _build_ownership_schema(conn) -> None:
    """Build the ownership schema + the extra reclaim/emit tables on ``conn``."""
    _create_ownership_schema(conn)
    apply_ddl_statements(conn, EMIT_PATH_TABLES)


@pytest.fixture
def ownership_conn(tmp_path):
    """Backend-aware conn with full ownership schema; per-test DB on both engines.

    Mirrors the legacy fixture: full ownership schema + extra reclaim/emit
    tables, a seeded runnable item (id 100), and the strategy SML files the
    scheduler coherence check reads. See :func:`conn` for the backend rationale.
    """
    with init_test_db(
        tmp_path, apply_schema=lambda: _apply_on_backend(_build_ownership_schema)
    ):
        c = _connect_with_backend_setup(tmp_path)
        # Seed a runnable item (matches the legacy fixture).
        c.execute(
            "INSERT INTO items (id, title, type, status, priority, project_id, "
            "project_sequence, "
            "created_at, updated_at, source, frozen) VALUES "
            "(100, 'Test item', 'issue', 'refined-idea', 'high', 1, 100, "
            "'2026-03-01', '2026-03-01', 'user', 0)"
        )
        c.commit()
        # Create SML files so scheduler sees SML as coherent
        ws = str(tmp_path)
        (tmp_path / ".yoke" / "strategy").mkdir(parents=True, exist_ok=True)
        for sml_file in ("MISSION.md", "LANDSCAPE.md", "VISION.md", "MASTER-PLAN.md"):
            (tmp_path / ".yoke" / "strategy" / sml_file).write_text(
                f"# {sml_file}\n"
            )
        try:
            yield c, ws
        finally:
            c.close()


def _ensure_active_session(
    conn,
    session_id: str,
    workspace: str,
    *,
    executor: str = "DARIUS",
    provider: str = "anthropic",
    model: str = TEST_MODEL_ID,
    execution_lane: str = "primary",
) -> None:
    row = conn.execute(
        f"SELECT session_id FROM harness_sessions WHERE session_id = {_p(conn)} "
        "AND ended_at IS NULL",
        (session_id,),
    ).fetchone()
    if row is not None:
        return
    register_session(
        conn,
        session_id=session_id,
        executor=executor,
        provider=provider,
        model=model,
        workspace=workspace,
        project_id=1,
        execution_lane=execution_lane,
    )
