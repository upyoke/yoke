"""Parse + explicit-ref extraction — TestParseHookEvent, TestExplicitRefExtraction."""

from __future__ import annotations

from yoke_core.domain.observe import parse_hook_event


class TestParseHookEvent:


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
    def test_public_ref_without_db_attributes_nothing(self):
        """The number in ``PREFIX-N`` is a project sequence; with no
        control-plane read there is no item id to attribute."""
        data = {
            "tool_name": "Bash",
            "tool_input": {"command": "sh script.sh YOK-1091"},
            "tool_response": {"content": "ok"},
        }
        rec = parse_hook_event(data, hook_event="PostToolUse")
        assert rec is not None
        assert rec.item_id is None

    def test_worktree_path_without_db_attributes_nothing(self):
        data = {
            "tool_name": "Read",
            "tool_input": {"file_path": "/repo/.worktrees/YOK-9999/src/main.py"},
            "tool_response": {"content": "code"},
        }
        rec = parse_hook_event(data, hook_event="PostToolUse")
        assert rec is not None
        assert rec.item_id is None

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
        """Multiple different public refs should not resolve."""
        data = {
            "tool_name": "Bash",
            "tool_input": {"command": "diff YOK-1 YOK-2"},
            "tool_response": {"content": ""},
        }
        rec = parse_hook_event(data, hook_event="PostToolUse", item_id="99")
        assert rec is not None
        # Ambiguous -- original item_id preserved when no single ref wins.
        assert rec.item_id == "99"

    def test_explicit_overrides_stale_marker(self):
        data = {
            "tool_name": "Bash",
            "tool_input": {"command": "sh script.sh --item 50"},
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
