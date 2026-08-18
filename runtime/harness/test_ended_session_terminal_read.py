"""Leftover Cursor terminal Reads must not revive an ended session."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from yoke_core.hooks.ended_session_terminal_read import (
    skip_ended_session_revival,
)
from yoke_core.hooks.types import HookContext


_TERMINAL = "/Users/x/.cursor/projects/Users-x/terminals/267595.txt"
_OTHER_CURSOR = "/Users/x/.cursor/projects/Users-x/hooks.json"


def _payload(**overrides):
    body = {
        "hook_event_name": "PreToolUse",
        "tool_name": "Read",
        "tool_input": {"file_path": _TERMINAL},
    }
    body.update(overrides)
    return body


def _ctx(**overrides) -> HookContext:
    payload = overrides.pop("payload", _payload())
    fields = {
        "event_name": "PreToolUse",
        "executor_family": "cursor",
        "executor_surface": "cursor-desktop",
        "payload": payload,
        "tool_name": "Read",
        "command_body": None,
        "cwd": "/tmp",
        "session_id": "s-1",
        "item_id": None,
        "now": datetime.now(timezone.utc),
    }
    fields.update(overrides)
    return HookContext(**fields)


def test_skips_cursor_project_terminal_read():
    assert skip_ended_session_revival(_payload()) is True


def test_skips_post_tool_use_and_camel_event():
    assert skip_ended_session_revival(
        _payload(hook_event_name="postToolUse"),
    ) is True
    assert skip_ended_session_revival(
        _payload(hook_event_name="preToolUse"),
    ) is True


def test_skips_string_tool_input_and_windows_separators():
    assert skip_ended_session_revival(
        _payload(tool_input=_TERMINAL),
    ) is True
    win = r"C:\Users\x\.cursor\projects\Users-x\terminals\1.txt"
    assert skip_ended_session_revival(_payload(tool_input={"path": win})) is True


def test_skips_hook_context():
    assert skip_ended_session_revival(_ctx()) is True


@pytest.mark.parametrize(
    "payload",
    [
        _payload(hook_event_name="UserPromptSubmit"),
        _payload(hook_event_name="SessionStart"),
        _payload(tool_name="Bash", tool_input={"command": f"cat {_TERMINAL}"}),
        _payload(tool_name="Write", tool_input={"file_path": _TERMINAL}),
        _payload(tool_input={"file_path": _OTHER_CURSOR}),
        _payload(tool_input={"file_path": "/tmp/readme.md"}),
        {"session_id": "s-1"},
        {},
    ],
)
def test_does_not_skip_other_hooks_or_paths(payload):
    assert skip_ended_session_revival(payload) is False


@pytest.mark.parametrize("executor", ["claude-code", "claude", "codex"])
def test_does_not_skip_claude_or_codex(executor):
    assert skip_ended_session_revival(
        _payload(), executor_hint=executor,
    ) is False


def test_skips_cursor_family_hints():
    assert skip_ended_session_revival(
        _payload(), executor_hint="cursor-desktop",
    ) is True
    assert skip_ended_session_revival(_payload(), executor_hint="") is True
