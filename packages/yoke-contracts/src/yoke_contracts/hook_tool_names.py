"""Native hook tool names in the canonical chain vocabulary.

The universal hook chains are keyed on ``Bash`` and ``Edit``. Every shell
tool a harness declares in :mod:`yoke_contracts.harness_shell_tools` (Claude
``PowerShell``, Cursor ``Shell``, Codex ``shell``) runs the ``Bash`` chain;
the shell it runs is carried separately as the payload's shell kind. Cursor
names its replace edit ``StrReplace``, and its shell gate
(``beforeShellExecution``) carries no ``tool_name`` at all, only a top-level
``command``, and still runs the ``Bash`` chain. Every reader that selects a
chain from a hook payload resolves the tool through :func:`payload_tool_name`
— the client collecting facts, the resident routing a call, and the server
canonicalizing the payload — or a shell call resolves to the guard-free
``_default`` chain on one side and the ``Bash`` chain on the other.
"""

from __future__ import annotations

from typing import Mapping

from yoke_contracts.cursor_shell_timing import CURSOR_SHELL_EVENTS
from yoke_contracts.harness_shell_tools import SHELL_CHAIN_MATCHER, SHELL_TOOL_NAMES


# Only names that differ are listed; others pass through unchanged.
TOOL_NAME_CANONICAL: Mapping[str, str] = {
    **{name: SHELL_CHAIN_MATCHER for name in SHELL_TOOL_NAMES},
    "StrReplace": "Edit",
}


def canonical_tool_name(tool_name: str) -> str:
    return TOOL_NAME_CANONICAL.get(tool_name, tool_name)


def payload_tool_name(payload: Mapping[str, object]) -> str | None:
    """Return the chain-vocabulary tool name a hook payload runs under.

    A named tool maps through :data:`TOOL_NAME_CANONICAL`; a Cursor shell
    gate without one is ``Bash``. Anything else names no tool.
    """
    tool_name = payload.get("tool_name")
    if isinstance(tool_name, str) and tool_name:
        return canonical_tool_name(tool_name)
    if payload.get("hook_event_name") in CURSOR_SHELL_EVENTS:
        return SHELL_CHAIN_MATCHER
    return None


__all__ = ["TOOL_NAME_CANONICAL", "canonical_tool_name", "payload_tool_name"]
