"""Client adapter for engine-owned Dash and Blitz worktree preparation."""

from __future__ import annotations

import subprocess
import sys
from typing import Callable, Dict, List, Tuple

from yoke_cli.commands._helpers import client_project_context
from yoke_contracts.item_ref import parse_public_item_ref

AdapterFn = Callable[[List[str]], int]
PREPARE_USAGE = (
    "yoke direct-workflow worktree prepare ITEM --workflow dash|blitz "
    "[--project P] [--session-id S] [--json]"
)


def direct_workflow_worktree_prepare(args: List[str]) -> int:
    """Delegate local engine mutation without importing engine authority."""
    forwarded = list(args)
    prefix, sequence = parse_public_item_ref(forwarded[0] if forwarded else None)
    has_project = any(
        arg == "--project" or arg.startswith("--project=") for arg in forwarded
    )
    if prefix is None and sequence is not None and not has_project:
        project = client_project_context()
        if project is not None:
            forwarded.extend(("--project", project))
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "yoke_core.domain.direct_workflow_worktree_preflight",
            *forwarded,
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
