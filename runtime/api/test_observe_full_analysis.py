"""Duration computation + per-session anomaly analysis."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from yoke_core.domain.observe import (
    EventRecord,
    build_envelope,
    detect_anomalies,
    insert_event,
    parse_hook_event,
)
from runtime.api.fixtures.file_test_db import connect_test_db
from runtime.api.observe_full_test_helpers import (
    make_events_db_conn,
    make_events_db_file,
)


@pytest.fixture
def events_db():
    conn = make_events_db_conn()
    yield conn
    conn.close()


@pytest.fixture
def events_db_file(tmp_path):
    with make_events_db_file(tmp_path) as db_path:
        yield db_path


class TestDuration:
    def test_duration_with_session_tool_call(self, events_db_file):
        """Duration is computed from active session tool-call state."""
        tuid = f"tu-{uuid.uuid4()}"
        now = datetime.now(timezone.utc)
        start_time = (
            now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"
        )

        conn = connect_test_db(events_db_file)
        conn.execute(
            "CREATE TABLE session_tool_calls ("
            "session_id TEXT NOT NULL, tool_use_id TEXT NOT NULL, "
            "started_at TEXT NOT NULL)"
        )
        conn.execute(
            "INSERT INTO session_tool_calls (session_id, tool_use_id, started_at) "
            "VALUES ('sess', %s, %s)",
            (
                tuid,
                start_time,
            ),
        )
        conn.commit()
        conn.close()

        data = {
            "tool_name": "Bash",
            "tool_input": {"command": "echo hi"},
            "tool_response": {"content": "hi"},
        }
        rec = parse_hook_event(
            data,
            hook_event="PostToolUse",
            tool_use_id=tuid,
            db_path=events_db_file,
        )
        assert rec is not None
        assert rec.duration_ms is not None

    def test_duration_null_no_pre(self):
        """TC-duration-null-no-pre: duration_ms NULL without HarnessToolCallStarted."""
        data = {
            "tool_name": "Bash",
            "tool_input": {"command": "echo hi"},
            "tool_response": {"content": "hi"},
        }
        rec = parse_hook_event(
            data,
            hook_event="PostToolUse",
            tool_use_id="tu-nopre",
            db_path=None,
        )
        assert rec is not None
        assert rec.duration_ms is None

    def test_duration_null_no_tool_use_id(self):
        """TC-duration-no-tuid: duration_ms NULL without tool_use_id."""
        data = {
            "tool_name": "Bash",
            "tool_input": {"command": "echo hi"},
            "tool_response": {"content": "hi"},
        }
        rec = parse_hook_event(data, hook_event="PostToolUse")
        assert rec is not None
        assert rec.duration_ms is None


class TestSessionAnalysis:
    def test_separate_structured_from_real_failures(self, events_db):
        """TC-47: Session analysis can separate structured exits from real failures."""
        rec1 = EventRecord(
            tool_name="Bash",
            is_failure=True,
            hook_error="Awaiting human approval",
            session_id="s-analysis",
        )
        detect_anomalies(rec1)
        env1 = build_envelope(rec1)
        insert_event(events_db, env1)

        rec2 = EventRecord(
            tool_name="Bash",
            is_failure=True,
            hook_error="command not found",
            session_id="s-analysis",
        )
        detect_anomalies(rec2)
        env2 = build_envelope(rec2)
        insert_event(events_db, env2)

        structured = events_db.execute(
            "SELECT count(*) FROM events WHERE event_name = 'HarnessToolCallStructuredExit'"
        ).fetchone()[0]
        assert structured == 1

        real_failures = events_db.execute(
            "SELECT count(*) FROM events WHERE event_name = 'HarnessToolCallFailed'"
        ).fetchone()[0]
        assert real_failures == 1
