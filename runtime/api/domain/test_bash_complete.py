"""Tests for bash_complete.py — PostToolUse/Bash hook owner."""

from __future__ import annotations

import json

from yoke_core.domain.bash_complete import (
    detect_script_failure,
    extract_hook_command,
    extract_hook_output,
)


class TestExtractHookCommand:
    def test_extracts_command(self):
        payload = json.dumps({"tool_input": {"command": "echo hello"}})
        assert extract_hook_command(payload) == "echo hello"

    def test_invalid_payload_returns_empty(self):
        assert extract_hook_command("not-json") == ""


class TestExtractHookOutput:
    def test_extracts_string_content(self):
        payload = json.dumps({"tool_response": {"content": "done"}})
        assert extract_hook_output(payload) == "done"

    def test_extracts_list_content(self):
        payload = json.dumps(
            {
                "tool_response": {
                    "content": [
                        {"text": "alpha"},
                        {"text": "beta"},
                    ]
                }
            }
        )
        assert extract_hook_output(payload) == "alpha beta"


class TestDetectScriptFailure:
    def test_skips_non_yoke_commands(self):
        assert detect_script_failure("echo hello", "Exit code 1") is None

    def test_returns_log_entry_for_failed_yoke_script(self):
        entry = detect_script_failure(
            "sh .agents/skills/yoke/scripts/example.sh",
            "line1\nExit code 7\nline3",
        )
        assert entry is not None
        assert "exit_code=7" in entry
        assert ".agents/skills/yoke/scripts/example.sh" in entry
