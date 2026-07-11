"""Tests for yoke_core.domain.events_retired_name_guard.

The guard refuses ``event_registry.status='retired'``
names on both sanctioned insertion paths (``emit_event`` and
``cmd_insert``) and writes no row when it refuses. Active and
unregistered names pass; missing ``event_registry`` table is a no-op so
minimal-schema test DBs are not broken.
"""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from yoke_core.domain import db_backend
from yoke_core.domain.schema_init_apply import execute_schema_script
from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db
from yoke_core.domain.events import emit_event
from yoke_core.domain.events_retired_name_guard import (
    RetiredEventNameError,
    assert_event_name_not_retired,
)
from yoke_core.domain.events_writes import cmd_insert


def _create_events_table(conn) -> None:
    execute_schema_script(
        conn,
        """
        CREATE TABLE IF NOT EXISTS projects (
            id INTEGER PRIMARY KEY,
            slug TEXT NOT NULL UNIQUE,
            name TEXT NOT NULL DEFAULT '',
            public_item_prefix TEXT NOT NULL DEFAULT 'YOK'
        );
        INSERT INTO projects (id, slug, name, public_item_prefix)
        VALUES (1, 'yoke', 'Yoke', 'YOK')
        ON CONFLICT(id) DO NOTHING;
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY,
            event_id TEXT UNIQUE NOT NULL,
            source_type TEXT NOT NULL,
            session_id TEXT NOT NULL,
            severity TEXT NOT NULL DEFAULT 'INFO',
            event_kind TEXT NOT NULL,
            event_type TEXT NOT NULL,
            event_name TEXT NOT NULL,
            event_outcome TEXT,
            org_id TEXT, actor_id INTEGER, environment TEXT,
            service TEXT NOT NULL DEFAULT 'cli',
            project_id INTEGER NOT NULL DEFAULT 1 REFERENCES projects(id),
            item_id TEXT, task_num INTEGER, agent TEXT, tool_name TEXT,
            duration_ms INTEGER, exit_code INTEGER,
            trace_id TEXT, parent_id TEXT, anomaly_flags TEXT,
            tool_use_id TEXT, turn_id TEXT, hook_event_name TEXT,
            envelope TEXT,
            created_at TEXT NOT NULL
        );
        """
    )


def _create_event_registry(conn) -> None:
    execute_schema_script(
        conn,
        """
        CREATE TABLE IF NOT EXISTS event_registry (
            event_name TEXT PRIMARY KEY,
            event_kind TEXT,
            event_type TEXT,
            owner_service TEXT,
            description TEXT,
            context_schema TEXT,
            severity_default TEXT DEFAULT 'INFO',
            added_in TEXT,
            status TEXT NOT NULL DEFAULT 'active'
        );
        """
    )


def _seed_registry(conn) -> None:
    p = "%s" if db_backend.connection_is_postgres(conn) else "?"
    for event_name, status in [
        ("ToolCallCompleted", "retired"),
        ("HarnessToolCallCompleted", "active"),
        ("BodyRegenerated", "retired"),
    ]:
        conn.execute(
            f"INSERT INTO event_registry (event_name, status) VALUES ({p}, {p})",
            (event_name, status),
        )
    conn.commit()


@pytest.fixture
def db_file(tmp_path):
    def _apply() -> None:
        conn = db_backend.connect()
        _create_events_table(conn)
        _create_event_registry(conn)
        _seed_registry(conn)
        conn.commit()
        conn.close()

    with init_test_db(tmp_path, apply_schema=_apply) as path:
        yield path


def _row_count(db_path: str) -> int:
    conn = connect_test_db(db_path)
    try:
        return conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    finally:
        conn.close()


def test_assert_raises_for_retired_name(db_file):
    conn = connect_test_db(db_file)
    try:
        with pytest.raises(RetiredEventNameError) as excinfo:
            assert_event_name_not_retired(conn, "ToolCallCompleted")
        assert excinfo.value.event_name == "ToolCallCompleted"
        assert excinfo.value.successor_name == "HarnessToolCallCompleted"
        assert "HarnessToolCallCompleted" in str(excinfo.value)
    finally:
        conn.close()


def test_assert_raises_with_generic_hint_when_no_direct_successor(db_file):
    conn = connect_test_db(db_file)
    try:
        with pytest.raises(RetiredEventNameError) as excinfo:
            assert_event_name_not_retired(conn, "BodyRegenerated")
        assert excinfo.value.event_name == "BodyRegenerated"
        assert excinfo.value.successor_name is None
        assert "active replacement from event_registry" in str(excinfo.value)
    finally:
        conn.close()


def test_assert_noop_for_active_name(db_file):
    conn = connect_test_db(db_file)
    try:
        assert_event_name_not_retired(conn, "HarnessToolCallCompleted")
    finally:
        conn.close()


def test_assert_noop_for_unregistered_name(db_file):
    conn = connect_test_db(db_file)
    try:
        assert_event_name_not_retired(conn, "NeverRegisteredName")
    finally:
        conn.close()


def test_assert_noop_when_event_registry_missing(tmp_path):
    def _apply() -> None:
        conn = db_backend.connect()
        try:
            _create_events_table(conn)  # no event_registry table
            conn.commit()
        finally:
            conn.close()

    with init_test_db(tmp_path, apply_schema=_apply) as path:
        conn = connect_test_db(path)
        try:
            assert_event_name_not_retired(conn, "AnythingAtAll")
        finally:
            conn.close()


def test_assert_noop_when_db_path_unopenable():
    # Bad path: the guard fails open so the native emit_event non-fatal
    # contract (test_emit_returns_none_on_bad_db_path) is preserved.
    assert_event_name_not_retired("/nonexistent/dir/missing.db", "AnythingAtAll")


def test_assert_noop_when_db_path_is_none():
    assert_event_name_not_retired(None, "AnythingAtAll")


def test_emit_event_refuses_retired_name(db_file):
    with pytest.raises(RetiredEventNameError):
        emit_event(
            "ToolCallCompleted",
            event_kind="lifecycle",
            event_type="domain",
            db_path=db_file,
        )
    assert _row_count(db_file) == 0


def test_emit_event_writes_active_name_with_connection(db_file):
    conn = connect_test_db(db_file)
    try:
        result = emit_event(
            "HarnessToolCallCompleted",
            event_kind="lifecycle",
            event_type="domain",
            conn=conn,
        )
        assert result.ok is True
        count = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        assert count == 1
    finally:
        conn.close()


def test_cmd_insert_refuses_retired_name(db_file):
    with pytest.raises(RetiredEventNameError):
        cmd_insert(
            db_path=db_file,
            event_id="evt-retired-1",
            source_type="backend",
            session_id="sess-1",
            event_kind="lifecycle",
            event_type="domain",
            event_name="ToolCallCompleted",
            skip_severity=True,
        )
    assert _row_count(db_file) == 0


def test_cmd_insert_writes_active_name(db_file):
    cmd_insert(
        db_path=db_file,
        event_id="evt-active-1",
        source_type="backend",
        session_id="sess-1",
        event_kind="lifecycle",
        event_type="domain",
        event_name="HarnessToolCallCompleted",
        skip_severity=True,
    )
    assert _row_count(db_file) == 1
