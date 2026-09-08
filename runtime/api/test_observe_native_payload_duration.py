"""Native payload duration is preferred over start-row elapsed time."""

from __future__ import annotations

from yoke_core.domain.observe_parsing import parse_hook_event


def test_native_duration_is_used_without_tool_use_id() -> None:
    rec = parse_hook_event(
        {
            "tool_name": "Bash",
            "tool_input": {"command": "true"},
            "duration_ms": 25,
            "session_id": "sess-native",
        },
        hook_event="PostToolUse",
    )
    assert rec is not None
    assert rec.duration_ms == 25
    assert rec.tool_use_id is None


def test_native_duration_wins_over_missing_start_row() -> None:
    rec = parse_hook_event(
        {
            "tool_name": "Bash",
            "tool_input": {"command": "true"},
            "tool_use_id": "tu-native",
            "duration_ms": 12,
            "session_id": "sess-native",
        },
        hook_event="PostToolUse",
    )
    assert rec is not None
    assert rec.duration_ms == 12
