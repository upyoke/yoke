"""Shared payload builders for the lint_long_command_polling pytest suites."""

from __future__ import annotations


def _bash_payload(
    command: str,
    *,
    description: str = "",
    session_id: str = "sess-test",
    turn_id: str = "turn-1",
    tool_use_id: str = "tu-1",
) -> dict:
    return {
        "tool_name": "Bash",
        "tool_input": {"command": command, "description": description},
        "session_id": session_id,
        "tool_use_id": tool_use_id,
        "turn_id": turn_id,
    }


def _non_bash_payload(
    tool_name: str,
    *,
    session_id: str = "sess-test",
    turn_id: str = "turn-1",
    tool_use_id: str = "tu-1",
    tool_input: dict | None = None,
) -> dict:
    return {
        "tool_name": tool_name,
        "tool_input": tool_input or {"delaySeconds": 120, "reason": "checking build"},
        "session_id": session_id,
        "tool_use_id": tool_use_id,
        "turn_id": turn_id,
    }
