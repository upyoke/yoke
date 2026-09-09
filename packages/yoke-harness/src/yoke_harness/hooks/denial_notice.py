"""Append client-side explanation to a relayed denial without corrupting it.

A denial reaches the operator as the hook's stdout, which is either plain
text or a harness deny envelope. Facts only the client holds — the guard
revision it is running, the machine-config mapping the server cannot see —
belong in that same output, so the appending has to understand both shapes.
"""

from __future__ import annotations

import json
from typing import Any

_HOOK_OUTPUT_KEY = "hookSpecificOutput"


def append_notice(text: str, notice: str, *, marker: str) -> str:
    """Append ``notice`` to ``text`` unless ``marker`` is already present."""
    if marker and marker in text:
        return text
    return f"{text.rstrip()}\n\n{notice}" if text.strip() else notice


def _annotate_hook_envelope(payload: dict[str, Any], notice: str, marker: str) -> bool:
    inner = payload.get(_HOOK_OUTPUT_KEY)
    if not isinstance(inner, dict) or inner.get("permissionDecision") != "deny":
        return False
    reason = inner.get("permissionDecisionReason")
    if not isinstance(reason, str):
        return False
    inner["permissionDecisionReason"] = append_notice(reason, notice, marker=marker)
    return True


def _annotate_cursor_envelope(payload: dict[str, Any], notice: str, marker: str) -> bool:
    if payload.get("permission") != "deny":
        return False
    changed = False
    for key in ("user_message", "agent_message"):
        value = payload.get(key)
        if isinstance(value, str):
            payload[key] = append_notice(value, notice, marker=marker)
            changed = True
    return changed


def annotate_denial(stdout: str, notice: str, *, marker: str) -> str:
    """Add ``notice`` to a denial's stdout, plain text or deny envelope."""
    if not notice:
        return stdout
    try:
        payload = json.loads(stdout)
    except (json.JSONDecodeError, TypeError):
        return append_notice(stdout, notice, marker=marker)
    if not isinstance(payload, dict):
        return stdout
    if not (
        _annotate_hook_envelope(payload, notice, marker)
        or _annotate_cursor_envelope(payload, notice, marker)
    ):
        return stdout
    return json.dumps(payload)


__all__ = ["annotate_denial", "append_notice"]
