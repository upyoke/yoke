"""Tests for yoke_core.domain.events -- envelope + connection-mode emit.

Covers envelope construction and direct DB writes via a sqlite3 connection.
Non-fatal degradation checks live in test_events_emit.py.
"""

from __future__ import annotations

import json
import os
import sys

import pytest

# Ensure the repo root is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from yoke_core.domain.events import (
    MAX_CONTEXT_FIELD_BYTES,
    build_envelope,
    emit_event,
)
from runtime.api.fixtures.pg_testdb import test_database


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def conn():
    """Provide an isolated backend-aware connection with events schema."""
    with test_database() as c:
        yield c


# ---------------------------------------------------------------------------
# build_envelope tests
# ---------------------------------------------------------------------------


class TestBuildEnvelope:
    def test_basic_envelope(self):
        env = build_envelope(
            "TestEvent",
            event_kind="system",
            event_type="test",
            source_type="backend",
            session_id="sess-1",
        )
        assert env["event_name"] == "TestEvent"
        assert env["event_kind"] == "system"
        assert env["event_type"] == "test"
        assert env["source_type"] == "backend"
        assert env["session_id"] == "sess-1"
        assert env["severity"] == "INFO"
        assert env["event_outcome"] == "completed"
        assert env["service"] == "cli"
        assert env["project"] == "yoke"
        assert "event_id" in env
        assert "created_at" in env

    def test_context_included(self):
        env = build_envelope(
            "TestEvent",
            event_kind="system",
            event_type="test",
            context={"key": "value"},
        )
        assert env["context"] == {"key": "value"}

    def test_context_field_size_limit(self):
        long_value = "x" * (MAX_CONTEXT_FIELD_BYTES + 100)
        env = build_envelope(
            "TestEvent",
            event_kind="system",
            event_type="test",
            context={"big": long_value},
        )
        assert len(env["context"]["big"]) == MAX_CONTEXT_FIELD_BYTES

    def test_envelope_size_limit_shrinks_per_value(self):
        # One huge NESTED value (dicts dodge the per-field string cap)
        # plus small identity scalars: the shrink replaces only the huge
        # value with a marker; the scalars audits key on survive.
        huge = {"docs": [{"file_text": "x" * 200_000}]}
        env = build_envelope(
            "TestEvent",
            event_kind="system",
            event_type="test",
            context={
                "function": "strategy.render.run",
                "request_id": "req-123",
                "result_byte_count": 200_041,
                "result": huge,
            },
        )
        ctx = env["context"]
        assert ctx["function"] == "strategy.render.run"
        assert ctx["request_id"] == "req-123"
        assert ctx["result_byte_count"] == 200_041
        assert ctx["_truncated"] is True
        assert ctx["result"]["_truncated_value"] is True
        assert ctx["result"]["_bytes"] > 200_000
        assert len(json.dumps(env)) <= 65536

    def test_envelope_size_limit_shrinks_largest_first(self):
        # Two oversized values, one bigger: only as many values as
        # needed are replaced, starting with the largest.
        env = build_envelope(
            "TestEvent",
            event_kind="system",
            event_type="test",
            context={
                "function": "f.run",
                "bigger": {"blob": "y" * 120_000},
                "smaller": {"blob": "z" * 10_000},
            },
        )
        ctx = env["context"]
        assert ctx["bigger"]["_truncated_value"] is True
        assert ctx["smaller"] == {"blob": "z" * 10_000}
        assert ctx["function"] == "f.run"

    def test_envelope_size_limit_pathological_fallback(self):
        # So many keys that even all-markers exceeds the cap: the old
        # whole-context marker is the final fallback.
        huge_context = {f"key-{i:05d}": "x" * 1000 for i in range(3000)}
        env = build_envelope(
            "TestEvent",
            event_kind="system",
            event_type="test",
            context=huge_context,
        )
        assert env["context"] == {"_truncated": True}

    def test_optional_fields(self):
        env = build_envelope(
            "TestEvent",
            event_kind="system",
            event_type="test",
            item_id="42",
            task_num=3,
            duration_ms=100,
            exit_code=0,
            trace_id="trace-1",
            anomaly_flags="nonzero_exit",
        )
        assert env["item_id"] == "42"
        assert env["task_num"] == 3
        assert env["duration_ms"] == 100
        assert env["exit_code"] == 0
        assert env["trace_id"] == "trace-1"
        assert env["anomaly_flags"] == "nonzero_exit"

    def test_correlation_fields_in_envelope(self):
        """Verify tool-call correlation uses session_id as the canonical join key."""
        env = build_envelope(
            "CorrelationTest",
            event_kind="system",
            event_type="tool_call",
            session_id="hs-session-1",
            tool_use_id="toolu_abc123",
            turn_id="turn-42",
            hook_event_name="PostToolUse",
        )
        assert env["tool_use_id"] == "toolu_abc123"
        assert env["session_id"] == "hs-session-1"
        assert env["turn_id"] == "turn-42"
        assert env["hook_event_name"] == "PostToolUse"

    def test_correlation_fields_default_none(self):
        """Correlation fields default to None when omitted."""
        env = build_envelope(
            "NoCorrelation",
            event_kind="system",
            event_type="test",
        )
        assert env["tool_use_id"] is None
        assert env["turn_id"] is None
        assert env["hook_event_name"] is None


# ---------------------------------------------------------------------------
# emit_event tests — with connection
# ---------------------------------------------------------------------------


class TestEmitEventWithConn:
    def test_emit_inserts_row(self, conn):
        result = emit_event(
            "TestEmit",
            event_kind="system",
            event_type="test",
            source_type="backend",
            session_id="sess-1",
            conn=conn,
        )
        assert result is not None
        assert result["event_name"] == "TestEmit"

        row = conn.execute(
            "SELECT * FROM events WHERE event_name = 'TestEmit'"
        ).fetchone()
        assert row is not None
        assert row["session_id"] == "sess-1"
        assert row["source_type"] == "backend"

    def test_emit_with_item_id(self, conn):
        emit_event(
            "ItemEvent",
            event_kind="lifecycle",
            event_type="test",
            session_id="s1",
            item_id="99",
            task_num=5,
            conn=conn,
        )
        row = conn.execute(
            "SELECT item_id, task_num FROM events WHERE event_name = 'ItemEvent'"
        ).fetchone()
        assert row["item_id"] == "99"
        assert row["task_num"] == 5

    def test_envelope_json_is_valid(self, conn):
        emit_event(
            "JsonCheck",
            event_kind="system",
            event_type="test",
            session_id="s1",
            context={"nested": {"key": "val"}},
            conn=conn,
        )
        row = conn.execute(
            "SELECT envelope FROM events WHERE event_name = 'JsonCheck'"
        ).fetchone()
        parsed = json.loads(row["envelope"])
        assert parsed["context"]["nested"]["key"] == "val"

    def test_emit_with_correlation_fields(self, conn):
        """Verify correlation columns are stored in the DB row."""
        emit_event(
            "CorrEvent",
            event_kind="system",
            event_type="tool_call",
            session_id="s1",
            tool_use_id="toolu_xyz",
            turn_id="turn-7",
            hook_event_name="PostToolUse",
            conn=conn,
        )
        row = conn.execute(
            "SELECT session_id, tool_use_id, turn_id, hook_event_name "
            "FROM events WHERE event_name = 'CorrEvent'"
        ).fetchone()
        assert row["session_id"] == "s1"
        assert row["tool_use_id"] == "toolu_xyz"
        assert row["turn_id"] == "turn-7"
        assert row["hook_event_name"] == "PostToolUse"

    def test_emit_correlation_fields_null_when_omitted(self, conn):
        """Correlation fields are NULL when not provided."""
        emit_event(
            "NoCorrEvent",
            event_kind="system",
            event_type="test",
            session_id="s1",
            conn=conn,
        )
        row = conn.execute(
            "SELECT tool_use_id, turn_id, hook_event_name "
            "FROM events WHERE event_name = 'NoCorrEvent'"
        ).fetchone()
        assert row["tool_use_id"] is None
        assert row["turn_id"] is None
        assert row["hook_event_name"] is None

    def test_duplicate_event_id_ignored(self, conn):
        """Native conflict handling prevents duplicate event_id crashes."""
        result1 = emit_event(
            "Dup",
            event_kind="system",
            event_type="test",
            session_id="s1",
            conn=conn,
        )
        # Manually insert the same event_id to simulate a race
        assert result1 is not None
        conn.execute(
            "INSERT INTO events (event_id, event_name, event_kind, "
            "event_type, source_type, session_id, severity, service, "
            "project_id, created_at) VALUES (%s, 'Dup2', 'system', 'test', "
            "'backend', 's1', 'INFO', 'cli', 1, %s) "
            "ON CONFLICT(event_id) DO NOTHING",
            (result1["event_id"], "2026-04-20T00:00:00Z"),
        )
        conn.commit()

        count = conn.execute(
            "SELECT COUNT(*) FROM events WHERE event_id = %s",
            (result1["event_id"],),
        ).fetchone()[0]
        assert count == 1
