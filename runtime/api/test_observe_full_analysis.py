"""Duration computation + per-session anomaly analysis."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from yoke_core.domain.observe import (
    EventRecord,
    build_envelope,
    detect_anomalies,
    insert_event,
    parse_hook_event,
)
from yoke_core.domain.observe_timing import (
    TIMING_MEASURED,
    TIMING_UNKNOWN_NO_CALL_IDENTITY,
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
        """Duration spans the call's captured start and completion."""
        tuid = f"tu-{uuid.uuid4()}"
        # The stored start keeps milliseconds, so derive the completion from
        # the truncated value: measuring against a microsecond-precise "now"
        # leaves a sub-millisecond remainder that rounds either way.
        started = datetime.now(timezone.utc).replace(microsecond=0)
        start_time = started.strftime("%Y-%m-%dT%H:%M:%S.000Z")
        completed = started + timedelta(milliseconds=750)

        conn = connect_test_db(events_db_file)
        conn.execute(
            "CREATE TABLE session_tool_calls ("
            "session_id TEXT NOT NULL, tool_use_id TEXT NOT NULL, "
            "started_at TEXT NOT NULL, completed_at TEXT)"
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
            session_id="sess",
            hook_event="PostToolUse",
            tool_use_id=tuid,
            db_path=events_db_file,
            completed_at=completed,
        )
        assert rec is not None
        assert rec.duration_ms == 750
        assert rec.timing_status == TIMING_MEASURED

    def test_duration_null_no_pre(self):
        """TC-duration-null-no-pre: duration_ms NULL without HarnessToolCallStarted."""
        data = {
            "tool_name": "Bash",
            "tool_input": {"command": "echo hi"},
            "tool_response": {"content": "hi"},
        }
        rec = parse_hook_event(
            data,
            session_id="sess",
            hook_event="PostToolUse",
            tool_use_id="tu-nopre",
            db_path=None,
            completed_at=datetime.now(timezone.utc),
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
        assert rec.timing_status == TIMING_UNKNOWN_NO_CALL_IDENTITY


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
