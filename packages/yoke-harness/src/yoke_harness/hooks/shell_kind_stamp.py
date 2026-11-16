"""Stamp the shell a command is written for onto hook stdin, client-side.

The harness manifest's ``shell_tools`` says which shell each shell tool runs;
``os_default`` tools (Codex, Cursor) run PowerShell on Windows and Bash
elsewhere. Only this machine knows its operating system, so the client
resolves the kind here and writes it to the payload before any evaluation,
local or relayed. The native tool name stays as sent: the evaluating side
canonicalizes it (``hook_tool_names.canonicalize_shell_payload``), so a server
older than the stamp keeps its own behavior for a tool it does not know.
"""

from __future__ import annotations

import json

from yoke_contracts.cursor_shell_timing import CURSOR_SHELL_EVENTS
from yoke_contracts.executor_labels import canonical_harness_id
from yoke_contracts.harness_shell_tools import (
    SHELL_KIND_PAYLOAD_KEY,
    is_windows,
    shell_kind_for,
)


def stamp_shell_kind(stdin_data: str, executor: str, *, windows: bool | None = None) -> str:
    """Return hook stdin with the shell kind stamped on a shell-tool payload."""
    if not stdin_data:
        return stdin_data
    try:
        harness_id = canonical_harness_id(executor)
        payload = json.loads(stdin_data)
    except ValueError:
        return stdin_data
    if not isinstance(payload, dict) or SHELL_KIND_PAYLOAD_KEY in payload:
        return stdin_data
    tool_name = payload.get("tool_name")
    if not isinstance(tool_name, str) or not tool_name:
        if payload.get("hook_event_name") not in CURSOR_SHELL_EVENTS:
            return stdin_data
        tool_name = ""
    kind = shell_kind_for(
        harness_id, tool_name, windows=is_windows() if windows is None else windows
    )
    if kind is None:
        return stdin_data
    payload[SHELL_KIND_PAYLOAD_KEY] = kind
    return json.dumps(payload)


__all__ = ["stamp_shell_kind"]
