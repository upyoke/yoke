"""Cursor shell-gate timing: native primitives vs explicit unsupported."""

from __future__ import annotations

import json

import pytest

from yoke_contracts.cursor_session_map import (
    CURSOR_SESSION_MAP_DIR_NAME,
    record_conversation_session,
)
from yoke_contracts.cursor_shell_timing import (
    CURSOR_SHELL_TIMING_MEASURED,
    CURSOR_SHELL_TIMING_UNSUPPORTED_REASON,
    is_unsupported_cursor_shell_duration,
)
from yoke_core.hooks.cursor_payload import parse_payload

MAIN = "11111111-2222-3333-4444-555555555555"
SUB = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
TRANSCRIPT = f"/home/u/.cursor/projects/p/agent-transcripts/{MAIN}/{MAIN}.jsonl"


@pytest.fixture
def container_env(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = tmp_path / "machine-home"
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(home))
    record_conversation_session(MAIN, MAIN, home / CURSOR_SESSION_MAP_DIR_NAME)
    monkeypatch.delenv("YOKE_SESSION_ID", raising=False)
    monkeypatch.setenv("CURSOR_TRANSCRIPT_PATH", TRANSCRIPT)


def test_shell_gate_stamps_unsupported_timing_without_inventing_ids(
    container_env: None,
) -> None:
    first = parse_payload(
        json.dumps(
            {
                "hook_event_name": "beforeShellExecution",
                "command": "true",
                "session_id": MAIN,
                "conversation_id": MAIN,
            }
        )
    )
    second = parse_payload(
        json.dumps(
            {
                "hook_event_name": "beforeShellExecution",
                "command": "true",
                "session_id": MAIN,
                "conversation_id": MAIN,
            }
        )
    )
    assert first.get("tool_use_id") is None
    assert second.get("tool_use_id") is None
    assert first["cursor_shell_timing"] == CURSOR_SHELL_TIMING_UNSUPPORTED_REASON
    assert second["cursor_shell_timing"] == CURSOR_SHELL_TIMING_UNSUPPORTED_REASON


def test_after_shell_copies_native_duration_and_call_id(container_env: None) -> None:
    data = parse_payload(
        json.dumps(
            {
                "hook_event_name": "afterShellExecution",
                "command": "ls",
                "output": "ok",
                "call_id": "call-9",
                "duration_ms": 40,
                "session_id": MAIN,
            }
        )
    )
    assert data["tool_use_id"] == "call-9"
    assert data["duration_ms"] == 40
    assert data["cursor_shell_timing"] == CURSOR_SHELL_TIMING_MEASURED


def test_failed_shell_completion_stays_unsupported_without_id(
    container_env: None,
) -> None:
    data = parse_payload(
        json.dumps(
            {
                "hook_event_name": "afterShellExecution",
                "command": "false",
                "output": "boom",
                "error": "exit 1",
                "session_id": MAIN,
            }
        )
    )
    assert data.get("tool_use_id") is None
    assert data["cursor_shell_timing"] == CURSOR_SHELL_TIMING_UNSUPPORTED_REASON


def test_subagent_shell_folds_session_without_inventing_id(
    container_env: None,
) -> None:
    data = parse_payload(
        json.dumps(
            {
                "hook_event_name": "beforeShellExecution",
                "command": "pwd",
                "session_id": SUB,
                "conversation_id": SUB,
            }
        )
    )
    assert data["session_id"] == MAIN
    assert data["subagent_session_id"] == SUB
    assert data.get("tool_use_id") is None
    assert data["cursor_shell_timing"] == CURSOR_SHELL_TIMING_UNSUPPORTED_REASON


def test_non_shell_cursor_payloads_are_not_stamped(container_env: None) -> None:
    data = parse_payload(
        json.dumps(
            {
                "hook_event_name": "preToolUse",
                "tool_name": "Read",
                "tool_use_id": "tu-read",
                "session_id": MAIN,
            }
        )
    )
    assert "cursor_shell_timing" not in data
    assert data["tool_use_id"] == "tu-read"


def test_coverage_classifier_is_cursor_bash_without_id_only() -> None:
    assert is_unsupported_cursor_shell_duration(
        harness="cursor",
        tool_name="Bash",
        tool_use_id=None,
        duration_ms=None,
    )
    assert not is_unsupported_cursor_shell_duration(
        harness="claude-code",
        tool_name="Bash",
        tool_use_id=None,
        duration_ms=None,
    )
    assert not is_unsupported_cursor_shell_duration(
        harness="cursor",
        tool_name="Read",
        tool_use_id=None,
        duration_ms=None,
    )
    assert not is_unsupported_cursor_shell_duration(
        harness="cursor",
        tool_name="Bash",
        tool_use_id="tu-1",
        duration_ms=None,
    )
