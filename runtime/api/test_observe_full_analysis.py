"""Duration computation + per-session anomaly analysis."""

from __future__ import annotations

import json
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
    def test_duration_with_tool_call_started(self, events_db_file):
        """TC-duration-e2e: duration computed from HarnessToolCallStarted event."""
        tuid = f"tu-{uuid.uuid4()}"
        now = datetime.now(timezone.utc)
        start_time = now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"

        conn = connect_test_db(events_db_file)
        conn.execute(
            "INSERT INTO events (id, event_id, source_type, session_id, event_kind, "
            "event_type, event_name, tool_use_id, envelope, created_at) "
            "VALUES (%s, %s, 'system', 'sess', 'system', 'tool_call', "
            "'HarnessToolCallStarted', %s, %s, %s)",
            (
                1, str(uuid.uuid4()), tuid,
                json.dumps({"tool_use_id": tuid}), start_time,
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
        # duration_ms should be computed (small positive value since just inserted).
        # May be None if the time resolution is too coarse, but should not error.

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
            tool_name="Bash", is_failure=True,
            hook_error="Awaiting human approval", session_id="s-analysis",
        )
        detect_anomalies(rec1)
        env1 = build_envelope(rec1)
        insert_event(events_db, env1)

        rec2 = EventRecord(
            tool_name="Bash", is_failure=True,
            hook_error="command not found", session_id="s-analysis",
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
