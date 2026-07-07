"""TC-1..TC-10, TC-65..TC-68, response-text helpers — parse + dedup + extract."""

from __future__ import annotations

import pytest

from yoke_core.domain.observe import (
    EventRecord,
    build_envelope,
    detect_anomalies,
    insert_event,
    parse_hook_event,
    _extract_response_text,
)
from runtime.api.observe_full_test_helpers import (
    SAMPLE_BASH_FAILURE,
    SAMPLE_BASH_SUCCESS,
    SAMPLE_EDIT_FAILURE,
    SAMPLE_READ_EVENT,
    SAMPLE_WRITE_EVENT,
    make_events_db_conn,
)


@pytest.fixture
def events_db():
    conn = make_events_db_conn()
    yield conn
    conn.close()


class TestParseHookEvent:
    """TC-1 through TC-10: Basic parsing."""

    def test_bash_success(self):
        """TC-1: HarnessToolCallCompleted on successful Bash."""
        rec = parse_hook_event(
            SAMPLE_BASH_SUCCESS,
            session_id="sess-1",
            agent_type="engineer",
            hook_event="PostToolUse",
        )
        assert rec is not None
        assert rec.tool_name == "Bash"
        assert rec.command == "echo hello"
        assert rec.exit_code == 0
        assert rec.is_failure is False
        assert rec.session_id == "sess-1"
        assert rec.agent_type == "engineer"

    def test_bash_failure_exit_code(self):
        """TC-9: Exit code parsed from Bash output."""
        rec = parse_hook_event(
            SAMPLE_BASH_FAILURE,
            hook_event="PostToolUseFailure",
        )
        assert rec is not None
        assert rec.exit_code == 1
        assert rec.is_failure is True

    def test_edit_failure(self):
        """TC-2: HarnessToolCallFailed on PostToolUseFailure."""
        rec = parse_hook_event(
            SAMPLE_EDIT_FAILURE,
            hook_event="PostToolUseFailure",
        )
        assert rec is not None
        assert rec.is_failure is True
        assert rec.hook_error == "String to replace not found in file"

    def test_write_file_path(self):
        """TC-10: Non-Bash tool types recorded correctly."""
        rec = parse_hook_event(SAMPLE_WRITE_EVENT, hook_event="PostToolUse")
        assert rec is not None
        assert rec.tool_name == "Write"
        assert rec.file_path == "/tmp/output.txt"
        assert rec.command == ""

    def test_read_file_path(self):
        """TC-10: Read tool records file_path."""
        rec = parse_hook_event(SAMPLE_READ_EVENT, hook_event="PostToolUse")
        assert rec is not None
        assert rec.tool_name == "Read"
        assert rec.file_path == "/tmp/input.py"

    def test_edit_file_path(self):
        """TC-10: Edit tool records file_path."""
        data = {
            "tool_name": "Edit",
            "tool_input": {"file_path": "/tmp/edit.py"},
            "tool_response": {"content": "ok"},
        }
        rec = parse_hook_event(data, hook_event="PostToolUse")
        assert rec is not None
        assert rec.file_path == "/tmp/edit.py"

    def test_item_id_strips_sun_prefix(self):
        rec = parse_hook_event(
            SAMPLE_BASH_SUCCESS, item_id="42", hook_event="PostToolUse"
        )
        assert rec is not None
        assert rec.item_id == "42"

    def test_empty_item_id_becomes_none(self):
        rec = parse_hook_event(
            SAMPLE_BASH_SUCCESS, item_id="", hook_event="PostToolUse"
        )
        assert rec is not None
        assert rec.item_id is None

    def test_numeric_item_id_kept(self):
        rec = parse_hook_event(
            SAMPLE_BASH_SUCCESS, item_id="99", hook_event="PostToolUse"
        )
        assert rec is not None
        assert rec.item_id == "99"

    def test_agent_type_propagated(self):
        """TC-14: Agent attribution via agent_type kwarg."""
        rec = parse_hook_event(
            SAMPLE_BASH_SUCCESS,
            agent_type="tester",
            hook_event="PostToolUse",
        )
        assert rec is not None
        assert rec.agent_type == "tester"

    def test_agent_null_when_absent(self):
        """TC-15: Agent NULL when no agent_type — main session."""
        rec = parse_hook_event(
            SAMPLE_BASH_SUCCESS, hook_event="PostToolUse"
        )
        assert rec is not None
        assert rec.agent_type is None

    def test_task_num_propagated(self):
        """TC-8: Dispatch context enrichment (task_num)."""
        rec = parse_hook_event(
            SAMPLE_BASH_SUCCESS,
            task_num=5,
            hook_event="PostToolUse",
        )
        assert rec is not None
        assert rec.task_num == 5

    def test_session_id_propagated(self):
        rec = parse_hook_event(
            SAMPLE_BASH_SUCCESS,
            session_id="sess-abc",
            hook_event="PostToolUse",
        )
        assert rec is not None
        assert rec.session_id == "sess-abc"

    def test_empty_payload_returns_record(self):
        """Gracefully handles minimal payload."""
        data = {"tool_name": "", "tool_input": {}, "tool_response": {}}
        rec = parse_hook_event(data, hook_event="PostToolUse")
        assert rec is not None
        assert rec.tool_name == ""

    def test_none_tool_input(self):
        """Handles None tool_input without crashing."""
        data = {"tool_name": "Bash", "tool_input": None, "tool_response": {}}
        rec = parse_hook_event(data, hook_event="PostToolUse")
        assert rec is not None
        assert rec.command == ""

    def test_command_truncated_at_4096(self):
        """Long commands are truncated at 4096 chars."""
        long_cmd = "x" * 5000
        data = {
            "tool_name": "Bash",
            "tool_input": {"command": long_cmd},
            "tool_response": {"content": "ok"},
        }
        rec = parse_hook_event(data, hook_event="PostToolUse")
        assert rec is not None
        assert len(rec.command) == 4096


class TestDedupLogic:
    """TC-65 through TC-68: PostToolUse/PostToolUseFailure deduplication."""

    def test_post_tool_use_drops_failure(self):
        """TC-65: PostToolUse skips emission for failed tool calls."""
        rec = parse_hook_event(
            SAMPLE_EDIT_FAILURE,
            hook_event="PostToolUse",
        )
        assert rec is None

    def test_post_tool_use_failure_emits(self):
        """TC-66: PostToolUseFailure emits HarnessToolCallFailed normally."""
        rec = parse_hook_event(
            SAMPLE_EDIT_FAILURE,
            hook_event="PostToolUseFailure",
        )
        assert rec is not None
        assert rec.is_failure is True

    def test_post_tool_use_passes_success(self):
        """TC-67: PostToolUse emits HarnessToolCallCompleted for successes."""
        rec = parse_hook_event(
            SAMPLE_BASH_SUCCESS,
            hook_event="PostToolUse",
        )
        assert rec is not None
        assert rec.is_failure is False

    def test_both_hooks_same_failure_one_row(self, events_db):
        """TC-68: Both hooks on same failure produces exactly one row."""
        rec1 = parse_hook_event(
            SAMPLE_BASH_FAILURE,
            hook_event="PostToolUse",
            session_id="dedup-test",
        )
        assert rec1 is None

        rec2 = parse_hook_event(
            SAMPLE_BASH_FAILURE,
            hook_event="PostToolUseFailure",
            session_id="dedup-test",
        )
        assert rec2 is not None
        detect_anomalies(rec2)
        env = build_envelope(rec2)
        insert_event(events_db, env)

        count = events_db.execute("SELECT count(*) FROM events").fetchone()[0]
        assert count == 1


class TestExtractResponseText:
    def test_dict_string_content(self):
        assert _extract_response_text({"content": "hello"}) == "hello"

    def test_dict_list_content(self):
        resp = {"content": [{"text": "a"}, {"text": "b"}]}
        result = _extract_response_text(resp)
        assert "a" in result and "b" in result

    def test_string_response(self):
        assert _extract_response_text("raw string") == "raw string"

    def test_none_response(self):
        assert _extract_response_text(None) == ""

    def test_empty_dict(self):
        assert _extract_response_text({}) == ""

    def test_list_with_non_dict_items(self):
        resp = {"content": ["text1", "text2"]}
        result = _extract_response_text(resp)
        assert "text1" in result

    def test_truncation_at_4096(self):
        long_content = "x" * 5000
        result = _extract_response_text({"content": long_content})
        assert len(result) == 4096
