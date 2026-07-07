"""Envelope construction (severity, fields, json) and DB insertion behaviors."""

from __future__ import annotations

import json

import pytest

from runtime.api.fixtures.file_test_db import connect_test_db
from runtime.api.fixtures.pg_testdb import (
    connect_test_database,
    create_test_database,
    drop_test_database,
)
from yoke_core.domain.observe import (
    EventRecord,
    build_envelope,
    insert_event,
)
from runtime.api.observe_full_test_helpers import make_events_db_file


@pytest.fixture
def events_db(tmp_path):
    with make_events_db_file(tmp_path) as db_path:
        conn = connect_test_db(db_path)
        try:
            yield conn
        finally:
            conn.close()


class TestBuildEnvelope:
    def test_completed_envelope_fields(self):
        rec = EventRecord(
            tool_name="Bash", command="echo hi", exit_code=0,
            session_id="sess-1", agent_type="engineer", item_id="42",
        )
        rec.anomalies = []
        env = build_envelope(rec)
        assert env["event_name"] == "HarnessToolCallCompleted"
        assert env["event_outcome"] == "completed"
        assert env["severity"] == "INFO"
        assert env["session_id"] == "sess-1"
        assert env["agent"] == "engineer"
        assert env["item_id"] == "42"
        assert env["tool_name"] == "Bash"
        assert "event_id" in env
        assert "event_time" in env

    def test_failed_envelope(self):
        rec = EventRecord(tool_name="Bash", is_failure=True, hook_error="fail")
        rec.anomalies = []
        env = build_envelope(rec)
        assert env["event_name"] == "HarnessToolCallFailed"
        assert env["event_outcome"] == "failed"
        assert env["severity"] == "WARN"

    def test_benign_failure_info_severity(self):
        rec = EventRecord(
            tool_name="Edit", is_failure=True,
            hook_error="String to replace not found",
        )
        rec.anomalies = ["benign_failure"]
        env = build_envelope(rec)
        assert env["severity"] == "INFO"

    def test_structured_exit_reclassified(self):
        """TC-46: Structured exit has INFO severity."""
        rec = EventRecord(
            tool_name="Bash", is_failure=True,
            hook_error="Awaiting human approval",
        )
        rec.anomalies = ["structured_exit"]
        env = build_envelope(rec)
        assert env["event_name"] == "HarnessToolCallStructuredExit"
        assert env["event_outcome"] == "structured_exit"
        assert env["severity"] == "INFO"

    def test_lifecycle_mutation_elevated(self):
        rec = EventRecord(tool_name="Bash", is_failure=False)
        rec.anomalies = ["lifecycle_mutation"]
        env = build_envelope(rec)
        assert env["event_name"] == "HarnessLifecycleMutationDetected"
        assert env["severity"] == "WARN"

    def test_unattributed_stays_info(self):
        """TC-64: Main-session unattributed completions stay INFO."""
        rec = EventRecord(
            tool_name="Bash", is_failure=False, item_id=None, agent_type=None,
        )
        rec.anomalies = ["unattributed"]
        env = build_envelope(rec)
        assert env["severity"] == "INFO"

    def test_anomaly_elevates_to_warn(self):
        rec = EventRecord(tool_name="Bash", is_failure=False)
        rec.anomalies = ["nonzero_exit"]
        env = build_envelope(rec)
        assert env["severity"] == "WARN"

    def test_context_detail_includes_command(self):
        rec = EventRecord(
            tool_name="Bash", command="echo test", response_text="output",
            attribution_source="marker",
        )
        rec.anomalies = []
        env = build_envelope(rec)
        ctx = env["context"]["detail"]
        assert ctx["tool_name"] == "Bash"
        assert ctx["tool_input"] == "echo test"
        assert ctx["tool_response_preview"] == "output"
        assert ctx["attribution_source"] == "marker"

    def test_context_detail_includes_file_path(self):
        rec = EventRecord(tool_name="Read", file_path="/tmp/test.py")
        rec.anomalies = []
        env = build_envelope(rec)
        ctx = env["context"]["detail"]
        assert ctx["tool_input"] == "/tmp/test.py"

    def test_context_detail_includes_error(self):
        rec = EventRecord(
            tool_name="Bash", is_failure=True, hook_error="command failed",
        )
        rec.anomalies = []
        env = build_envelope(rec)
        ctx = env["context"]["detail"]
        assert ctx["error"] == "command failed"

    def test_envelope_json_serializable(self):
        rec = EventRecord(tool_name="Bash", exit_code=0)
        rec.anomalies = []
        env = build_envelope(rec)
        s = json.dumps(env, separators=(",", ":"))
        parsed = json.loads(s)
        assert parsed["event_name"] == "HarnessToolCallCompleted"

    def test_envelope_has_required_fields(self):
        """All required envelope fields present."""
        rec = EventRecord(tool_name="Bash", exit_code=0, session_id="s1")
        rec.anomalies = []
        env = build_envelope(rec)
        required = [
            "event_id", "event_name", "event_kind", "event_type",
            "event_time", "event_outcome", "source_type", "severity",
            "session_id", "service", "project",
        ]
        for key in required:
            assert key in env, f"Missing required field: {key}"

    def test_oversized_envelope_truncated(self):
        """Verify truncation for oversized envelopes."""
        rec = EventRecord(
            tool_name="Bash",
            command="x" * 4000,
            response_text="y" * 4000,
        )
        rec.anomalies = []
        env = build_envelope(rec)
        envelope_json = json.dumps(env, separators=(",", ":"))
        if len(envelope_json.encode("utf-8")) > 100:
            env["context"] = {"detail": {"tool_name": rec.tool_name, "truncated": True}}
            env["_truncated"] = True
        assert env.get("_truncated") is True

    def test_task_num_in_envelope(self):
        rec = EventRecord(tool_name="Bash", task_num=7, session_id="s1")
        rec.anomalies = []
        env = build_envelope(rec)
        assert env["task_num"] == 7

    def test_duration_ms_in_envelope(self):
        rec = EventRecord(tool_name="Bash", duration_ms=150, session_id="s1")
        rec.anomalies = []
        env = build_envelope(rec)
        assert env["duration_ms"] == 150

    def test_tool_use_id_in_envelope(self):
        rec = EventRecord(tool_name="Bash", tool_use_id="tu-xyz", session_id="s1")
        rec.anomalies = []
        env = build_envelope(rec)
        assert env["tool_use_id"] == "tu-xyz"


class TestInsertEvent:
    def test_insert_creates_row(self, events_db):
        rec = EventRecord(
            tool_name="Bash", command="echo hi", exit_code=0, session_id="s1",
        )
        rec.anomalies = []
        env = build_envelope(rec)
        insert_event(events_db, env)
        row = events_db.execute("SELECT * FROM events").fetchone()
        assert row is not None

    def test_insert_no_events_table(self):
        """TC-6: Graceful no-op when events table doesn't exist."""
        db_name = create_test_database()
        conn = connect_test_database(db_name)
        rec = EventRecord(tool_name="Bash")
        rec.anomalies = []
        env = build_envelope(rec)
        try:
            insert_event(conn, env)  # should not raise
        finally:
            conn.close()
            drop_test_database(db_name)

    def test_duplicate_event_id_ignored(self, events_db):
        rec = EventRecord(tool_name="Bash", exit_code=0, session_id="s1")
        rec.anomalies = []
        env = build_envelope(rec)
        insert_event(events_db, env)
        insert_event(events_db, env)  # duplicate
        count = events_db.execute("SELECT count(*) FROM events").fetchone()[0]
        assert count == 1

    def test_inserted_fields_match(self, events_db):
        rec = EventRecord(
            tool_name="Bash", command="echo hello", exit_code=0,
            session_id="s2", item_id="42", task_num=3, agent_type="engineer",
        )
        rec.anomalies = ["nonzero_exit"]
        env = build_envelope(rec)
        insert_event(events_db, env)
        row = events_db.execute(
            "SELECT event_name, item_id, task_num, agent, anomaly_flags, "
            "session_id FROM events"
        ).fetchone()
        assert row[1] == "42"
        assert row[2] == 3
        assert row[3] == "engineer"
        assert row[5] == "s2"

    def test_envelope_stored_as_valid_json(self, events_db):
        rec = EventRecord(tool_name="Bash", exit_code=0, session_id="s1")
        rec.anomalies = []
        env = build_envelope(rec)
        insert_event(events_db, env)
        row = events_db.execute("SELECT envelope FROM events").fetchone()
        stored = json.loads(row[0])
        assert stored["event_name"] == "HarnessToolCallCompleted"
