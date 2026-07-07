"""Pure parsing/extraction helpers for the lint-event-registry hook.

Split out of :mod:`yoke_core.domain.lint_event_registry` to keep the
authored hook entry-point module under the 350-line cap. The hook
entry-point imports these helpers and uses them inside ``decide`` /
``run``; tests import them via re-exports on the entry-point module
path so the public hook surface stays stable.

Every helper here is pure: no DB access, no I/O, no exceptions raised
to the caller. Failures degrade to ``None`` / empty strings so the
hook stays fail-open at every layer.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Optional


# ``--name`` argument parsing. Double-quoted, single-quoted, and unquoted
# variants are all accepted, matching the pre-Pythonization shell behavior.
_NAME_RE_DOUBLE = re.compile(r'--name\s+"([^"]+)"')
_NAME_RE_SINGLE = re.compile(r"--name\s+'([^']+)'")
_NAME_RE_BARE = re.compile(r"--name\s+([^\s\"']+)")


@dataclass
class HookMeta:
    """Attribution metadata extracted from the PreToolUse payload."""

    session_id: str = ""
    tool_use_id: str = ""
    turn_id: str = ""
    command_snippet: str = ""


def parse_payload(raw: str) -> Optional[dict]:
    """Parse a PreToolUse JSON payload from *raw* stdin text.

    Returns the parsed dict, or ``None`` on any parse failure. An empty or
    blank payload also returns ``None``. Never raises.
    """
    if not raw or not raw.strip():
        return None
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    return data


def extract_command(data: dict) -> str:
    """Extract the Bash command string from a PreToolUse payload.

    Mirrors the same fallback chain as ``lint_db_cmd._extract_command``:
    ``tool_input.command`` → ``toolInput.command`` → ``input.command``
    → ``tool_input.cmd`` → top-level ``command``. Returns ``""`` when no
    command can be recovered.
    """
    for key in ("tool_input", "toolInput", "input"):
        sub = data.get(key)
        if isinstance(sub, dict):
            cmd = sub.get("command")
            if isinstance(cmd, str) and cmd != "":
                return cmd
            cmd = sub.get("cmd")
            if isinstance(cmd, str) and cmd != "":
                return cmd

    cmd = data.get("command")
    if isinstance(cmd, str):
        return cmd
    return ""


def extract_event_name(command: str) -> Optional[str]:
    """Return the ``--name`` argument value from *command*, or ``None``.

    Accepts double-quoted, single-quoted, and unquoted variants. Whitespace
    between ``--name`` and the value is tolerated (``\\s+``), matching the
    pre-Pythonization shell regex.
    """
    if not isinstance(command, str) or not command:
        return None
    for pattern in (_NAME_RE_DOUBLE, _NAME_RE_SINGLE, _NAME_RE_BARE):
        match = pattern.search(command)
        if match:
            return match.group(1)
    return None


def extract_hook_meta(data: dict) -> HookMeta:
    """Pull ``session_id`` / ``tool_use_id`` / ``turn_id`` / command from the payload.

    Missing fields become empty strings. ``turn_id`` falls back to
    ``message_id`` to match the previous shell extraction logic. The
    ``command_snippet`` is the Bash command text (if any) and carries into
    the HarnessToolCallDenied event context so operators can see which call
    was blocked.
    """
    if not isinstance(data, dict):
        return HookMeta()
    session_id = data.get("session_id") or ""
    tool_use_id = data.get("tool_use_id") or ""
    turn_id = data.get("turn_id") or data.get("message_id") or ""
    return HookMeta(
        session_id=str(session_id),
        tool_use_id=str(tool_use_id),
        turn_id=str(turn_id),
        command_snippet=extract_command(data),
    )
