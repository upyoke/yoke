"""Cursor shell-event timing: consume native primitives or name the gap.

``beforeShellExecution`` / ``afterShellExecution`` are Cursor's shell
gates. Cursor CLI 2026.09.02-c22c1a3 delivers ``command`` and ``sandbox``
on those events, and does not deliver ``tool_use_id`` or ``duration_ms``.
Yoke's observe-pre path requires ``tool_use_id`` to open rolling tool-call
state, so ID-less starts are dropped and the matching completions have no
duration. That is an unsupported surface, not a failed measurement.

When a later Cursor build adds a native correlation id or duration, copy
those fields through. Never invent an id, pair concurrent shells by
command text or arrival order, wrap native shell execution, or scan
transcripts on each hook.
"""

from __future__ import annotations

from typing import Any, Mapping

from yoke_contracts.harness_family_identity import CURSOR_FAMILY

CURSOR_SHELL_EVENTS = frozenset({"beforeShellExecution", "afterShellExecution"})
CURSOR_SHELL_TIMING_MEASURED = "measured"
CURSOR_SHELL_TIMING_UNSUPPORTED_REASON = (
    "cursor_shell_event_omits_tool_use_id_and_duration"
)
CURSOR_SHELL_TIMING_EVIDENCE = (
    "cursor-agent 2026.09.02-c22c1a3 beforeShellExecution/afterShellExecution "
    "payloads carry command and sandbox; they omit tool_use_id and duration_ms. "
    "Live Bash completions in that CLI have null id and null duration."
)
_NATIVE_ID_FIELDS = ("tool_use_id", "call_id")


def native_tool_use_id(data: Mapping[str, Any]) -> str | None:
    """Return a vendor-supplied correlation id, or None."""
    for key in _NATIVE_ID_FIELDS:
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def native_duration_ms(data: Mapping[str, Any]) -> int | None:
    """Return a vendor-supplied non-negative duration, or None."""
    value = data.get("duration_ms")
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def annotate_cursor_shell_payload(data: dict[str, Any]) -> None:
    """Copy native shell timing, or stamp the explicit unsupported reason."""
    if str(data.get("hook_event_name") or "") not in CURSOR_SHELL_EVENTS:
        return
    tool_id = native_tool_use_id(data)
    if tool_id:
        data["tool_use_id"] = tool_id
    duration = native_duration_ms(data)
    if duration is not None:
        data["duration_ms"] = duration
        data["cursor_shell_timing"] = CURSOR_SHELL_TIMING_MEASURED
        return
    if not tool_id:
        data["cursor_shell_timing"] = CURSOR_SHELL_TIMING_UNSUPPORTED_REASON


def is_unsupported_cursor_shell_duration(
    *,
    harness: str,
    tool_name: str | None,
    tool_use_id: str | None,
    duration_ms: int | None,
) -> bool:
    """True when a Cursor Bash completion has no id and no duration."""
    if duration_ms is not None:
        return False
    if str(harness or "").strip() != CURSOR_FAMILY:
        return False
    if str(tool_name or "").strip() != "Bash":
        return False
    return not str(tool_use_id or "").strip()


__all__ = [
    "CURSOR_SHELL_EVENTS",
    "CURSOR_SHELL_TIMING_EVIDENCE",
    "CURSOR_SHELL_TIMING_MEASURED",
    "CURSOR_SHELL_TIMING_UNSUPPORTED_REASON",
    "annotate_cursor_shell_payload",
    "is_unsupported_cursor_shell_duration",
    "native_duration_ms",
    "native_tool_use_id",
]
