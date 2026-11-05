# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

import contextlib

import tempfile

import unittest

from pathlib import Path

import yoke_core.domain.events_crud  # noqa: F401

from yoke_core.domain.events_queries import _build_where, cmd_list

from yoke_contracts.timestamps import parse_instant

from yoke_core.domain.schema_init_apply import execute_schema_script

from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db

_SCHEMA = """
CREATE TABLE projects (
    id INTEGER PRIMARY KEY,
    slug TEXT UNIQUE,
    name TEXT,
    public_item_prefix TEXT DEFAULT 'YOK'
);
INSERT INTO projects (id, slug, name, public_item_prefix)
VALUES (1, 'yoke', 'Yoke', 'YOK');
CREATE TABLE events (
    id INTEGER PRIMARY KEY,
    event_id TEXT,
    event_name TEXT NOT NULL,
    event_kind TEXT,
    event_type TEXT,
    event_outcome TEXT,
    source_type TEXT,
    session_id TEXT,
    project_id INTEGER,
    item_id TEXT,
    task_num INTEGER,
    context TEXT,
    outcome TEXT,
    severity TEXT,
    agent TEXT,
    service TEXT,
    actor_id INTEGER,
    environment TEXT,
    tool_name TEXT,
    tool_use_id TEXT,
    turn_id TEXT,
    duration_ms INTEGER,
    exit_code INTEGER,
    trace_id TEXT,
    anomaly_flags TEXT,
    client_timing_id TEXT,
    envelope TEXT,
    hook_event_name TEXT,
    created_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX idx_events_session_id ON events(session_id);
CREATE INDEX idx_events_created_at ON events(created_at);
CREATE TABLE harness_sessions (
    session_id TEXT PRIMARY KEY,
    episode_started_at TIMESTAMPTZ
);
"""


def _apply_events_schema() -> None:
    """``apply_schema`` strategy applying the local events-only ``_SCHEMA``.

    Resolves its connection through the backend factory (the repointed
    ``YOKE_PG_DSN``) so ``init_test_db`` builds the events table in the
    per-test database ``cmd_list`` reads back from.
    """
    from yoke_core.domain import db_backend

    conn = db_backend.connect()
    try:
        execute_schema_script(conn, _SCHEMA)
        conn.commit()
    finally:
        conn.close()


@contextlib.contextmanager
def _setup_db():
    """Yield a path-shaped ``db_path`` token with ``_SCHEMA`` applied.

    ``init_test_db`` provisions a disposable per-test database and repoints
    ``YOKE_PG_DSN`` for the context's lifetime, so the raw-insert
    ``connect_test_db`` calls and the ``cmd_list`` readback share one DB.
    """
    with tempfile.TemporaryDirectory(prefix="yoke-test-") as tmp_dir:
        with init_test_db(Path(tmp_dir), apply_schema=_apply_events_schema) as db_path:
            yield db_path


def _stamp_episode(db_path: str, session_id: str, at: str) -> None:
    """Record the episode boundary the way register_session does."""
    at = parse_instant(at)
    conn = connect_test_db(db_path)
    conn.execute(
        "INSERT INTO harness_sessions (session_id, episode_started_at) "
        "VALUES (%s, %s) "
        "ON CONFLICT(session_id) DO UPDATE SET episode_started_at = %s",
        (session_id, at, at),
    )
    conn.commit()
    conn.close()


def _insert_event(
    db_path: str,
    *,
    name: str,
    session_id: str,
    created_at: str,
    severity: str = "INFO",
    item_id: str = "",
) -> None:
    created_at = parse_instant(created_at)
    conn = connect_test_db(db_path)
    conn.execute(
        "INSERT INTO events (event_name, event_kind, event_type, source_type, "
        "session_id, project_id, item_id, severity, created_at) "
        "VALUES (%s, 'system', 'session_lifecycle', 'backend', %s, 1, %s, %s, %s)",
        (name, session_id, item_id or None, severity, created_at),
    )
    conn.commit()
    conn.close()
