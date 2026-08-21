"""Client adapter for the engine-owned advance implementation entry."""

from __future__ import annotations

import subprocess
import sys
from typing import Callable, Dict, List, Tuple

AdapterFn = Callable[[List[str]], int]
IMPLEMENTATION_ENTRY_USAGE = (
    "yoke advance implementation-entry --item ITEM "
    "[--no-worktree] [--force] [--qa-bypass] [--session-id S]"
)


def advance_implementation_entry(args: List[str]) -> int:
    """Delegate local engine mutation without importing engine authority."""
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "yoke_core.engines.advance_implementation_entry",
            *args,
        ],
        check=False,
    )
    return completed.returncode


TOOL_SHAPED_SUBCOMMANDS: Dict[Tuple[str, ...], AdapterFn] = {
    ("advance", "implementation-entry"): advance_implementation_entry,
}
TOOL_SHAPED_USAGE = {
    "yoke advance implementation-entry": IMPLEMENTATION_ENTRY_USAGE,
}


__all__ = [
    "IMPLEMENTATION_ENTRY_USAGE",
    "TOOL_SHAPED_SUBCOMMANDS",
    "TOOL_SHAPED_USAGE",
    "advance_implementation_entry",
]
