"""Client adapter for the engine-owned standalone-item merge."""

from __future__ import annotations

import subprocess
import sys
from yoke_cli.commands._helpers import show_delegate_help
from typing import Callable, Dict, List, Tuple


AdapterFn = Callable[[List[str]], int]
MERGE_ITEM_USAGE = (
    "yoke merge item ITEM --result TEXT --verification TEXT "
    "[--no-changes] [--target BRANCH] [--project P] [--skip-status] [--pr] "
    "[--wait] [--retry-flake TEST_AND_REASON] [--verification-status STATUS] [--session-id S] [--json]  (default queue route enqueues and exits; re-enter after "
    "landing; --no-changes is an existing lane only; a laneless no-change "
    "Dash uses dash evidence and its unique lifecycle edge)"
)


def merge_item(args: List[str]) -> int:
    """Delegate local merge authority without importing engine internals."""
    if show_delegate_help(
        args,
        MERGE_ITEM_USAGE,
        "Requires a committed, verified item lane and its work claim. The project merge policy owns landing.",
    ):
        return 0
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "yoke_cli.commands.merge_item_local_runtime",
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
