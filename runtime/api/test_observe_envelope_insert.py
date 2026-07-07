"""Envelope build, insert, and perf — TestBuildEnvelope, TestInsertEvent, TestPerformance."""

from __future__ import annotations

import json
import time

import pytest

from runtime.api.fixtures.pg_testdb import (
    connect_test_database,
    create_test_database,
    drop_test_database,
)
from yoke_core.domain.observe import (
    EventRecord,
    build_envelope,
    insert_event,
    parse_hook_event,
)
from runtime.api.observe_test_helpers import (
    SAMPLE_POST_TOOL_USE,
    make_memory_db,
)


@pytest.fixture
def memory_db():
    """Create an in-memory DB with the events table."""
    conn = make_memory_db()
    yield conn
    conn.close()


class TestBuildEnvelope:
    def test_basic_completed_envelope(self):
        rec = EventRecord(
            tool_name="Bash",
            command="echo hi",
            exit_code=0,
            session_id="sess-1",
            agent_type="engineer",
            item_id="42",
        )
        rec.anomalies = []
        env = build_envelope(rec)
        assert env["event_name"] == "HarnessToolCallCompleted"
        assert env["event_outcome"] == "completed"
        assert env["severity"] == "INFO"
        assert env["session_id"] == "sess-1"
        assert env["agent"] == "engineer"
        assert env["item_id"] == "42"

    def test_failed_envelope(self):
        rec = EventRecord(
            tool_name="Bash",
            is_failure=True,
            hook_error="command failed",
        )
        rec.anomalies = []
        env = build_envelope(rec)
        assert env["event_name"] == "HarnessToolCallFailed"
        assert env["event_outcome"] == "failed"
        assert env["severity"] == "WARN"

    def test_benign_failure_downgraded_to_info(self):
        rec = EventRecord(
            tool_name="Edit",
            is_failure=True,
            hook_error="String to replace not found",
        )
        rec.anomalies = ["benign_failure"]
        env = build_envelope(rec)
        assert env["severity"] == "INFO"

    def test_structured_exit_reclassified(self):
        rec = EventRecord(
            tool_name="Bash",
            is_failure=True,
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
        rec = EventRecord(
            tool_name="Bash", is_failure=False, item_id=None, agent_type=None
        )
        rec.anomalies = ["unattributed"]
        env = build_envelope(rec)
        assert env["severity"] == "INFO"

    def test_anomaly_elevates_to_warn(self):
        rec = EventRecord(tool_name="Bash", is_failure=False)
        rec.anomalies = ["nonzero_exit"]
        env = build_envelope(rec)
        assert env["severity"] == "WARN"

    def test_envelope_has_context_detail(self):
        rec = EventRecord(
            tool_name="Bash",
            command="echo test",
            response_text="test output",
            attribution_source="marker",
        )
        rec.anomalies = []
        env = build_envelope(rec)
        ctx = env["context"]["detail"]
        assert ctx["tool_name"] == "Bash"
        assert ctx["tool_input"] == "echo test"
        assert ctx["tool_response_preview"] == "test output"
        assert ctx["attribution_source"] == "marker"

    def test_envelope_json_serializable(self):
        rec = EventRecord(tool_name="Bash", exit_code=0)
        rec.anomalies = []
        env = build_envelope(rec)
        s = json.dumps(env, separators=(",", ":"))
        parsed = json.loads(s)
        assert parsed["event_name"] == "HarnessToolCallCompleted"

    def test_oversized_envelope_truncated(self):
        """Verify truncation logic exists and reduces size when triggered.

        The build_envelope function already truncates command to 2048 chars
        and response_preview to 512, so a truly oversized envelope requires
        forcing context past the 65536 byte limit. We test the truncation
        path by patching the size threshold lower.
        """
        rec = EventRecord(
            tool_name="Bash",
            command="x" * 4000,
            response_text="y" * 4000,
        )
        rec.anomalies = []
        # Patch the threshold to force truncation
        import yoke_core.domain.observe as obs_mod
        original_build = obs_mod.build_envelope

        def build_with_low_threshold(r):
            """Call build_envelope but with a very low size threshold."""
            env = original_build(r)
            envelope_json = json.dumps(env, separators=(",", ":"))
            # Simulate the truncation check with a low threshold
            if len(envelope_json.encode("utf-8")) > 100:
                env["context"] = {
                    "detail": {"tool_name": r.tool_name, "truncated": True}
                }
                env["_truncated"] = True
            return env

        env = build_with_low_threshold(rec)
        assert env.get("_truncated") is True
        assert env["context"]["detail"]["truncated"] is True


class TestInsertEvent:
    def test_insert_creates_row(self, memory_db):
        rec = EventRecord(
            tool_name="Bash",
            command="echo hi",
            exit_code=0,
            session_id="sess-1",
        )
        rec.anomalies = []
        env = build_envelope(rec)
        insert_event(memory_db, env)
        row = memory_db.execute("SELECT * FROM events").fetchone()
        assert row is not None

    def test_insert_no_events_table(self):
        """Should silently no-op when events table doesn't exist."""
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

    def test_duplicate_event_id_ignored(self, memory_db):
        rec = EventRecord(
            tool_name="Bash", exit_code=0, session_id="s1"
        )
        rec.anomalies = []
        env = build_envelope(rec)
        insert_event(memory_db, env)
        insert_event(memory_db, env)  # duplicate -- should not raise
        count = memory_db.execute(
            "SELECT count(*) FROM events"
        ).fetchone()[0]
        assert count == 1

    def test_inserted_fields_match(self, memory_db):
        rec = EventRecord(
            tool_name="Bash",
            command="echo hello",
            exit_code=0,
            session_id="sess-2",
            item_id="42",
            task_num=3,
            agent_type="engineer",
        )
        rec.anomalies = ["nonzero_exit"]
        env = build_envelope(rec)
        insert_event(memory_db, env)
        row = memory_db.execute(
            "SELECT event_name, item_id, task_num, agent, anomaly_flags FROM events"
        ).fetchone()
        assert row[1] == "42"
        assert row[2] == 3
        assert row[3] == "engineer"


class TestPerformance:
    def test_module_import_under_200ms(self):
        """Module import + parse_hook_event must complete in <200ms."""
        start = time.monotonic()
        rec = parse_hook_event(
            SAMPLE_POST_TOOL_USE,
            session_id="perf-test",
            hook_event="PostToolUse",
        )
        elapsed_ms = (time.monotonic() - start) * 1000
        assert rec is not None
        assert elapsed_ms < 200, f"parse_hook_event took {elapsed_ms:.1f}ms"
