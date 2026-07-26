"""Client adapter for engine-owned Dash and Blitz worktree preparation."""

from __future__ import annotations

import subprocess
import sys
from typing import Callable, Dict, List, Tuple

AdapterFn = Callable[[List[str]], int]
PREPARE_USAGE = (
    "yoke direct-workflow worktree prepare ITEM --workflow dash|blitz "
    "[--project P] [--session-id S]"
)


def direct_workflow_worktree_prepare(args: List[str]) -> int:
    """Delegate local engine mutation without importing engine authority."""
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "yoke_core.domain.direct_workflow_worktree_preflight",
            *args,
        ],
        check=False,
    )
    return completed.returncode


TOOL_SHAPED_SUBCOMMANDS: Dict[Tuple[str, ...], AdapterFn] = {
    ("direct-workflow", "worktree", "prepare"): (
        direct_workflow_worktree_prepare
    ),
}
TOOL_SHAPED_USAGE = {
    "yoke direct-workflow worktree prepare": PREPARE_USAGE,
}


__all__ = [
    "PREPARE_USAGE",
    "TOOL_SHAPED_SUBCOMMANDS",
    "TOOL_SHAPED_USAGE",
    "direct_workflow_worktree_prepare",
]
