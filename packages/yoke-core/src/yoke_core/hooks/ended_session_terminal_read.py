"""Skip ended-session revival for leftover Cursor terminal Reads.

Stop can already have emptied a Cursor session. Cursor then sometimes
fires PreToolUse/PostToolUse ``Read`` of leftover
``~/.cursor/projects/**/terminals/*.txt`` transcripts from earlier in
the same chat. Those Reads are not new work and must not reactivate the
ended row. Claude/Codex, live rows, lifecycle events, and any other
tool or path still revive as before.
"""

from __future__ import annotations

import json
import re
from typing import Any

from yoke_core.hooks.helpers_identity import is_claude, is_codex


_TOOL_EVENTS = frozenset({"pretooluse", "posttooluse"})
_READ_TOOLS = frozenset({"read"})
_TERMINAL_READ_RE = re.compile(
    r"(?:^|/)(?:\.cursor)/projects/.+/terminals/[^/]+\.txt$",
    re.IGNORECASE,
)


def skip_ended_session_revival(
    payload: Any = None,
    *,
    event_name: str = "",
    executor_hint: str = "",
) -> bool:
    """True when an ended row must stay ended for this hook payload."""
    data, resolved_event, tool_name, executor = _unpack(
        payload, event_name=event_name, executor_hint=executor_hint,
    )
    if is_claude(executor) or is_codex(executor):
        return False
    if resolved_event.casefold() not in _TOOL_EVENTS:
        return False
    if tool_name.casefold() not in _READ_TOOLS:
        return False
    return _is_cursor_project_terminal_path(_read_path(data))


def _unpack(
    payload: Any,
    *,
    event_name: str,
    executor_hint: str,
) -> tuple[dict[str, Any], str, str, str]:
    if (
        hasattr(payload, "payload")
        and hasattr(payload, "event_name")
    ):
        raw = payload.payload
        data = raw if isinstance(raw, dict) else {}
        event_name = event_name or str(getattr(payload, "event_name", "") or "")
        tool_name = str(getattr(payload, "tool_name", "") or "")
        executor_hint = executor_hint or str(
            getattr(payload, "executor_family", "") or ""
        )
    elif isinstance(payload, str):
        data = _parse_payload_json(payload)
        tool_name = ""
    elif isinstance(payload, dict):
        data = payload
        tool_name = ""
    else:
        return {}, event_name, "", executor_hint
    if not tool_name:
        raw_tool = data.get("tool_name")
        tool_name = raw_tool if isinstance(raw_tool, str) else ""
    if not event_name:
        raw_event = data.get("hook_event_name")
        event_name = raw_event if isinstance(raw_event, str) else ""
    return data, event_name, tool_name, executor_hint


def _parse_payload_json(payload_json: str) -> dict[str, Any]:
    if not payload_json:
        return {}
    try:
        parsed = json.loads(payload_json)
    except (json.JSONDecodeError, TypeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _read_path(payload: dict[str, Any]) -> str:
    tool_input = payload.get("tool_input")
    if isinstance(tool_input, str) and tool_input.strip():
        return tool_input.strip()
    if isinstance(tool_input, dict):
        for key in ("file_path", "path", "target_file", "file"):
            value = tool_input.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    for key in ("file_path", "path"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _is_cursor_project_terminal_path(raw_path: str) -> bool:
    if not raw_path:
        return False
    return bool(_TERMINAL_READ_RE.search(raw_path.replace("\\", "/")))


__all__ = ["skip_ended_session_revival"]
