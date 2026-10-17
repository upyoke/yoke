"""Cursor tool names in the canonical chain vocabulary.

Cursor names its shell tool ``Shell`` and its replace edit ``StrReplace``;
the universal hook chains are keyed on ``Bash`` and ``Edit``. Every reader
that selects a chain by tool name maps through this table first, or a Cursor
shell call resolves to the guard-free ``_default`` chain.
"""

from __future__ import annotations

from typing import Mapping


# Only names that differ are listed; others pass through unchanged.
CURSOR_TOOL_NAME_CANONICAL: Mapping[str, str] = {
    "Shell": "Bash",
    "StrReplace": "Edit",
}


def canonical_tool_name(tool_name: str) -> str:
    return CURSOR_TOOL_NAME_CANONICAL.get(tool_name, tool_name)


__all__ = ["CURSOR_TOOL_NAME_CANONICAL", "canonical_tool_name"]
