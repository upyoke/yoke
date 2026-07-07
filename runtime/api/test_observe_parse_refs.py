"""Parse + explicit-ref extraction — TestParseHookEvent, TestExplicitRefExtraction."""

from __future__ import annotations

from yoke_core.domain.observe import parse_hook_event
from runtime.api.observe_test_helpers import (
    SAMPLE_BASH_FAILURE,
    SAMPLE_POST_TOOL_USE,
    SAMPLE_POST_TOOL_USE_FAILURE,
)


class TestParseHookEvent:
    def test_basic_bash_event(self):
        rec = parse_hook_event(
            SAMPLE_POST_TOOL_USE,
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

    def test_failure_event(self):
        rec = parse_hook_event(
            SAMPLE_POST_TOOL_USE_FAILURE,
            hook_event="PostToolUseFailure",
        )
        assert rec is not None
        assert rec.is_failure is True
        assert rec.hook_error == "String to replace not found in file"

    def test_dedup_drops_post_tool_use_for_failure(self):
        """PostToolUse hook should be silently dropped for failures."""
        rec = parse_hook_event(
            SAMPLE_POST_TOOL_USE_FAILURE,
            hook_event="PostToolUse",
        )
        assert rec is None

    def test_dedup_allows_post_tool_use_failure(self):
        """PostToolUseFailure hook should NOT be dropped."""
        rec = parse_hook_event(
            SAMPLE_POST_TOOL_USE_FAILURE,
            hook_event="PostToolUseFailure",
        )
        assert rec is not None

    def test_item_id_keeps_numeric_form(self):
        rec = parse_hook_event(
            SAMPLE_POST_TOOL_USE,
            item_id="42",
            hook_event="PostToolUse",
        )
        assert rec is not None
        assert rec.item_id == "42"

    def test_empty_item_id_becomes_none(self):
        rec = parse_hook_event(
            SAMPLE_POST_TOOL_USE,
            item_id="",
            hook_event="PostToolUse",
        )
        assert rec is not None
        assert rec.item_id is None

    def test_read_file_path_extraction(self):
        data = {
            "tool_name": "Read",
            "tool_input": {"file_path": "/tmp/foo.py"},
            "tool_response": {"content": "file contents"},
        }
        rec = parse_hook_event(data, hook_event="PostToolUse")
        assert rec is not None
        assert rec.file_path == "/tmp/foo.py"

    def test_bash_exit_code_from_error(self):
        rec = parse_hook_event(
            SAMPLE_BASH_FAILURE,
            hook_event="PostToolUseFailure",
        )
        assert rec is not None
        assert rec.exit_code == 1

    def test_response_text_list_content(self):
        data = {
            "tool_name": "Bash",
            "tool_input": {"command": "ls"},
            "tool_response": {
                "content": [
                    {"text": "file1.txt"},
                    {"text": "file2.txt"},
                ]
            },
        }
        rec = parse_hook_event(data, hook_event="PostToolUse")
        assert rec is not None
        assert "file1.txt" in rec.response_text
        assert "file2.txt" in rec.response_text

    def test_response_text_string(self):
        data = {
            "tool_name": "Bash",
            "tool_input": {"command": "ls"},
            "tool_response": "raw string output",
        }
        rec = parse_hook_event(data, hook_event="PostToolUse")
        assert rec is not None
        assert rec.response_text == "raw string output"


class TestExplicitRefExtraction:
    def test_yok_n_in_bash_command(self):
        data = {
            "tool_name": "Bash",
            "tool_input": {"command": "sh script.sh YOK-1091"},
            "tool_response": {"content": "ok"},
        }
        rec = parse_hook_event(data, hook_event="PostToolUse")
        assert rec is not None
        assert rec.item_id == "1091"
        assert rec.attribution_source == "explicit_bash_ref"

    def test_worktree_path_in_read(self):
        data = {
            "tool_name": "Read",
            "tool_input": {"file_path": "/repo/.worktrees/YOK-9999/src/main.py"},
            "tool_response": {"content": "code"},
        }
        rec = parse_hook_event(data, hook_event="PostToolUse")
        assert rec is not None
        assert rec.item_id == "9999"
        assert rec.attribution_source == "explicit_path_ref"

    def test_items_get_numeric_ref(self):
        data = {
            "tool_name": "Bash",
            "tool_input": {"command": "python3 -m yoke_core.cli.db_router items get 55 status"},
            "tool_response": {"content": "active"},
        }
        rec = parse_hook_event(data, hook_event="PostToolUse")
        assert rec is not None
        assert rec.item_id == "55"
        assert rec.attribution_source == "explicit_bash_ref"

    def test_flag_ref(self):
        data = {
            "tool_name": "Bash",
            "tool_input": {"command": "sh deploy.sh --item 99"},
            "tool_response": {"content": "ok"},
        }
        rec = parse_hook_event(data, hook_event="PostToolUse")
        assert rec is not None
        assert rec.item_id == "99"
        assert rec.attribution_source == "explicit_bash_ref"

    def test_ambiguous_refs_no_override(self):
        """Multiple different YOK-N refs should not resolve."""
        data = {
            "tool_name": "Bash",
            "tool_input": {"command": "diff YOK-1 YOK-2"},
            "tool_response": {"content": ""},
        }
        rec = parse_hook_event(data, hook_event="PostToolUse", item_id="99")
        assert rec is not None
        # Ambiguous -- original item_id preserved when no single YOK-N ref wins.
        assert rec.item_id == "99"

    def test_explicit_overrides_stale_marker(self):
        data = {
            "tool_name": "Bash",
            "tool_input": {"command": "sh script.sh YOK-50"},
            "tool_response": {"content": "ok"},
        }
        rec = parse_hook_event(
            data,
            item_id="42",
            attribution_source="marker",
            hook_event="PostToolUse",
        )
        assert rec is not None
        assert rec.item_id == "50"
        assert rec.attribution_source == "explicit_bash_ref"
