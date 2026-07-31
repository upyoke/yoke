"""Client adapter for the engine-owned standalone-item merge."""

from __future__ import annotations

import subprocess
import sys
from typing import Callable, Dict, List, Tuple

AdapterFn = Callable[[List[str]], int]
MERGE_ITEM_USAGE = (
    "yoke merge item ITEM --result TEXT --verification TEXT "
    "[--no-changes] [--target BRANCH] [--project P] [--skip-status] [--pr]"
)


def merge_item(args: List[str]) -> int:
    """Delegate local merge authority without importing engine internals."""
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "yoke_core.domain.standalone_item_merge_cli",
            *args,
        ],
        check=False,
    )
    return completed.returncode


TOOL_SHAPED_SUBCOMMANDS: Dict[Tuple[str, ...], AdapterFn] = {
    ("merge", "item"): merge_item,
}
TOOL_SHAPED_USAGE = {
    "yoke merge item": MERGE_ITEM_USAGE,
}


__all__ = [
    "MERGE_ITEM_USAGE",
    "TOOL_SHAPED_SUBCOMMANDS",
    "TOOL_SHAPED_USAGE",
    "merge_item",
]
