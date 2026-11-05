# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

import contextlib

import shutil

import tempfile

import unittest

from datetime import datetime, timedelta, timezone

from pathlib import Path

from unittest import mock

from yoke_core.domain import db_backend

from runtime.api.reacquire_identity_test_support import _CREATE_IDENTITY

from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db

from runtime.api.sessions_api_stale_test_helpers import apply_ddl_statements

from yoke_core.domain.sessions_lifecycle_reactivation import (
    auto_reacquire_session_ended_claims,
    emit_reactivated_with_released_claims,
)

from yoke_core.domain.work_claim_targets import make_item_target, scope_int_sql

_CREATE_SESSIONS = """
CREATE TABLE IF NOT EXISTS harness_sessions (
    session_id TEXT PRIMARY KEY,
    executor TEXT NOT NULL,
    provider TEXT NOT NULL,
    model TEXT,
    reasoning_effort TEXT DEFAULT NULL, context_window_tokens INTEGER DEFAULT NULL, requested_model TEXT DEFAULT NULL, requested_reasoning_effort TEXT DEFAULT NULL, requested_context_window_tokens INTEGER DEFAULT NULL,
    execution_level TEXT NOT NULL DEFAULT 'primary',
    executor_version TEXT, machine_id TEXT,
    workspace TEXT NOT NULL DEFAULT '',
    mode TEXT NOT NULL DEFAULT 'wait',
    offered_at TIMESTAMPTZ NOT NULL,
    last_heartbeat TIMESTAMPTZ NOT NULL,
    ended_at TIMESTAMPTZ,
    offer_envelope TEXT,
    actor_id INTEGER,
    last_tool_call_at TIMESTAMPTZ,
    tool_call_count INTEGER NOT NULL DEFAULT 0,
    episode_started_at TIMESTAMPTZ,
    pending_resume_notice TEXT,
    current_item_id TEXT,
    current_item_set_at TIMESTAMPTZ,
    recent_item_id TEXT,
    recent_item_status TEXT,
    recent_item_recorded_at TIMESTAMPTZ
);
"""

_CREATE_WORK_CLAIMS = """
CREATE TABLE IF NOT EXISTS work_claims (
    id INTEGER PRIMARY KEY,
    session_id TEXT NOT NULL,
    target_kind TEXT NOT NULL,
    scope TEXT NOT NULL,
    claim_type TEXT NOT NULL DEFAULT 'exclusive',
    claimed_at TIMESTAMPTZ NOT NULL,
    last_heartbeat TIMESTAMPTZ NOT NULL,
    released_at TIMESTAMPTZ,
    release_reason TEXT
);
"""

_CREATE_EVENTS = """
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY,
    event_name TEXT NOT NULL,
    event_kind TEXT,
    event_type TEXT,
    source_type TEXT,
    session_id TEXT,
    project_id INTEGER,
    item_id TEXT,
    task_num INTEGER,
    context TEXT,
    client_timing_id TEXT,
    envelope TEXT,
    outcome TEXT,
    severity TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT (CURRENT_TIMESTAMP)
);
"""


def _apply_reacquire_schema() -> None:
    """``init_test_db`` strategy: build the minimal session/claim/event tables.

    Resolves the connection through the backend factory so the fixture DDL is
    applied to the repointed per-test Postgres database; the facade translates
    the SQLite-shaped ``INTEGER PRIMARY KEY`` DDL so the same constants seed
    the live authority.
    """
    conn = db_backend.connect()
    try:
        apply_ddl_statements(
            conn,
            _CREATE_SESSIONS,
            _CREATE_WORK_CLAIMS,
            _CREATE_EVENTS,
            _CREATE_IDENTITY,
        )
        conn.commit()
    finally:
        conn.close()


class _PgReacquireTestCase(unittest.TestCase):
    """Per-test disposable Postgres DB with the reactivation fixture schema."""

    def setUp(self) -> None:
        self._stack = contextlib.ExitStack()
        self._tmp_dir = tempfile.mkdtemp(prefix="yoke-test-reacquire-")
        self.db_path = self._stack.enter_context(
            init_test_db(Path(self._tmp_dir), apply_schema=_apply_reacquire_schema)
        )
        self.conn = connect_test_db(self.db_path)

    def tearDown(self) -> None:
        self.conn.close()
        self._stack.close()
        shutil.rmtree(self._tmp_dir, ignore_errors=True)


def _iso(delta_s: int = 0) -> str:
    return (
        (datetime.now(timezone.utc) + timedelta(seconds=delta_s))
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z")
    )


def _insert_session(conn, session_id: str) -> None:
    conn.execute(
        "INSERT INTO harness_sessions "
        "(session_id, executor, provider, model, workspace, offered_at, last_heartbeat) "
        "VALUES (%s, 'claude-code', 'anthropic', 'm', '/tmp', %s, %s)",
        (session_id, _iso(), _iso()),
    )
    conn.commit()


def _insert_released_claim(
    conn,
    session_id: str,
    item_id: int,
    *,
    released_age_s: int,
) -> None:
    conn.execute(
        "INSERT INTO work_claims "
        "(session_id, target_kind, scope, claim_type, claimed_at, "
        " last_heartbeat, released_at, release_reason) "
        "VALUES (%s, 'item', %s, 'exclusive', %s, %s, %s, 'session_ended')",
        (
            session_id,
            make_item_target(item_id).scope_json(),
            _iso(-released_age_s - 30),
            _iso(-released_age_s),
            _iso(-released_age_s),
        ),
    )
    conn.commit()
