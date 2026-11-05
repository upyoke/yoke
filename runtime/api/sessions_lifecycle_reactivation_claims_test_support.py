# ruff: noqa: E402, F401
"""Shared setup for tests in this directory."""

from __future__ import annotations

import tempfile

import unittest

from pathlib import Path

from unittest import mock

from typing import Any, Dict, Optional

from yoke_contracts.timestamps import parse_instant

from yoke_core.domain.sessions_analytics_core import (
    EVENT_SESSION_REACTIVATED_WITH_RELEASED_CLAIMS,
)

from yoke_core.domain.sessions_lifecycle_reactivation import (
    emit_reactivated_with_released_claims,
)

from yoke_core.domain.work_claim_targets import make_item_target

from runtime.api.fixtures.operating_actor import record_fixture_operating_actor

from yoke_core.domain.actors import seed_canonical_human, sole_human_actor_id

from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db

from runtime.api.fixtures.schema_ddl import apply_fixture_ddl

_CREATE_PROJECTS = """
CREATE TABLE IF NOT EXISTS projects (
    id INTEGER PRIMARY KEY,
    slug TEXT UNIQUE,
    name TEXT DEFAULT '',
    emoji TEXT DEFAULT '',
    public_item_prefix TEXT DEFAULT 'YOK'
);
INSERT INTO projects (id, slug, name, emoji, public_item_prefix)
VALUES (1, 'yoke', 'Yoke', '', 'YOK');
"""

_CREATE_SESSIONS = """
CREATE TABLE IF NOT EXISTS harness_sessions (
    session_id TEXT PRIMARY KEY, executor TEXT NOT NULL,
    executor_surface TEXT DEFAULT NULL, provider TEXT NOT NULL,
    model TEXT, execution_level TEXT NOT NULL DEFAULT 'primary',
    reasoning_effort TEXT DEFAULT NULL, context_window_tokens INTEGER DEFAULT NULL, requested_model TEXT DEFAULT NULL, requested_reasoning_effort TEXT DEFAULT NULL, requested_context_window_tokens INTEGER DEFAULT NULL,
    executor_version TEXT, machine_id TEXT, workspace TEXT NOT NULL DEFAULT '',
    project_id INTEGER NOT NULL,
    org_id INTEGER,
    mode TEXT NOT NULL DEFAULT 'wait', offered_at TIMESTAMPTZ NOT NULL,
    last_heartbeat TIMESTAMPTZ NOT NULL, ended_at TIMESTAMPTZ,
    terminated_at TIMESTAMPTZ, terminated_by_actor_id INTEGER,
    terminated_by_session_id TEXT, termination_reason TEXT,
    offer_envelope TEXT,
    actor_id INTEGER, last_tool_call_at TIMESTAMPTZ,
    tool_call_count INTEGER NOT NULL DEFAULT 0,
    episode_started_at TIMESTAMPTZ, pending_resume_notice TEXT
);
"""

_CREATE_WORK_CLAIMS = """
CREATE TABLE IF NOT EXISTS work_claims (
    id INTEGER PRIMARY KEY, session_id TEXT NOT NULL, target_kind TEXT NOT NULL,
    scope TEXT NOT NULL,
    claim_type TEXT NOT NULL DEFAULT 'exclusive',
    claimed_at TIMESTAMPTZ NOT NULL, last_heartbeat TIMESTAMPTZ NOT NULL,
    released_at TIMESTAMPTZ, release_reason TEXT
);
"""

_CREATE_EVENTS = """
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY, event_name TEXT NOT NULL, event_kind TEXT,
    event_type TEXT, source_type TEXT, session_id TEXT, project_id INTEGER,
    item_id TEXT, task_num INTEGER, context TEXT, outcome TEXT, severity TEXT,
    created_at TIMESTAMPTZ NOT NULL
);
"""

_CREATE_EVENT_REGISTRY = """
CREATE TABLE IF NOT EXISTS event_registry (event_name TEXT PRIMARY KEY,
    event_kind TEXT NOT NULL, event_type TEXT NOT NULL, owner_service TEXT NOT NULL,
    description TEXT NOT NULL, severity_default TEXT NOT NULL DEFAULT 'INFO');
"""

_CREATE_ACTORS = """
CREATE TABLE IF NOT EXISTS actors (status TEXT NOT NULL DEFAULT 'active',
    id INTEGER PRIMARY KEY,
    kind TEXT NOT NULL DEFAULT 'human',
    system_component TEXT,
    name TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ
);
"""

_CREATE_ORGANIZATIONS = """
CREATE TABLE IF NOT EXISTS organizations (
    id INTEGER PRIMARY KEY, slug TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL, created_at TIMESTAMPTZ NOT NULL
);
INSERT INTO organizations (id, slug, name, created_at)
    VALUES (1, 'default', 'Default', '2026-01-01T00:00:00Z')
    ON CONFLICT DO NOTHING;
"""


def _apply_reactivation_schema() -> None:
    """``apply_schema`` strategy building the fixture via the backend factory.

    ``register_session`` resolves its expected-exception type from
    ``db_backend``, so the seeding connection MUST be backend-resolved; a raw
    in-memory DB raises a different integrity exception than the Postgres
    default catches.
    """
    from yoke_core.domain import db_backend

    conn = db_backend.connect()
    try:
        apply_fixture_ddl(
            conn,
            _CREATE_PROJECTS
            + _CREATE_SESSIONS
            + _CREATE_WORK_CLAIMS
            + _CREATE_EVENTS
            + _CREATE_EVENT_REGISTRY
            + _CREATE_ACTORS
            + _CREATE_ORGANIZATIONS,
        )
        # Registration binds the universe's operating actor; a fixture
        # without one models an install that cannot exist.
        seed_canonical_human(conn)
        from runtime.api.fixtures.level_store import create_level_store_tables

        create_level_store_tables(conn)
    finally:
        conn.close()


def _insert_session(conn: Any, session_id: str, ended: bool = False) -> None:
    conn.execute(
        "INSERT INTO harness_sessions "
        "(session_id, executor, provider, model, workspace, project_id, offered_at, "
        "last_heartbeat, ended_at) "
        "VALUES (%s, 'claude-code', 'anthropic', 'test', '/tmp', 1, "
        "'2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z', %s)",
        (session_id, parse_instant("2026-01-01T01:00:00.123456Z") if ended else None),
    )
    conn.commit()


def _insert_claim(
    conn: Any,
    session_id: str,
    item_id: int,
    released: bool = False,
    release_reason: Optional[str] = None,
) -> int:
    cursor = conn.execute(
        "INSERT INTO work_claims "
        "(session_id, target_kind, scope, claim_type, claimed_at, last_heartbeat, "
        " released_at, release_reason) "
        "VALUES (%s, 'item', %s, 'exclusive', '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z', "
        "%s, %s) RETURNING id",
        (
            session_id,
            make_item_target(item_id).scope_json(),
            parse_instant("2026-01-01T01:00:00.123456Z") if released else None,
            release_reason if released else None,
        ),
    )
    row = cursor.fetchone()
    cursor.close()
    conn.commit()
    return int(row[0])


class _ReactivationDBTest(unittest.TestCase):
    """Per-test template checkout shared by seeding and registration."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._db_ctx = init_test_db(
            Path(self._tmp.name), apply_schema=_apply_reactivation_schema
        )
        self.db_path = self._db_ctx.__enter__()
        self.conn = connect_test_db(self.db_path)
        record_fixture_operating_actor(
            self.conn, sole_human_actor_id(self.conn, oldest=True)
        )

    def tearDown(self) -> None:
        self.conn.close()
        self._db_ctx.__exit__(None, None, None)
        self._tmp.cleanup()
