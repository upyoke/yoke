"""Cursor tool names in the canonical chain vocabulary.

Cursor names its shell tool ``Shell`` and its replace edit ``StrReplace``;
the universal hook chains are keyed on ``Bash`` and ``Edit``. Its shell gate
(``beforeShellExecution``) carries no ``tool_name`` at all, only a top-level
``command``, and still runs the ``Bash`` chain. Every reader that selects a
chain from a hook payload resolves the tool through
:func:`payload_tool_name` — the client collecting facts, the resident
routing a call, and the server canonicalizing the payload — or a Cursor
shell call resolves to the guard-free ``_default`` chain on one side and the
``Bash`` chain on the other.
"""

from __future__ import annotations

from typing import Mapping

from yoke_contracts.cursor_shell_timing import CURSOR_SHELL_EVENTS


# Only names that differ are listed; others pass through unchanged.
CURSOR_TOOL_NAME_CANONICAL: Mapping[str, str] = {
    "Shell": "Bash",
    "StrReplace": "Edit",
}


def canonical_tool_name(tool_name: str) -> str:
    return CURSOR_TOOL_NAME_CANONICAL.get(tool_name, tool_name)


def payload_tool_name(payload: Mapping[str, object]) -> str | None:
    """Return the chain-vocabulary tool name a hook payload runs under.

    A named tool maps through :data:`CURSOR_TOOL_NAME_CANONICAL`; a Cursor
    shell gate without one is ``Bash``. Anything else names no tool.
    """
    tool_name = payload.get("tool_name")
    if isinstance(tool_name, str) and tool_name:
        return canonical_tool_name(tool_name)
    if payload.get("hook_event_name") in CURSOR_SHELL_EVENTS:
        return "Bash"
    return None


__all__ = ["CURSOR_TOOL_NAME_CANONICAL", "canonical_tool_name", "payload_tool_name"]
