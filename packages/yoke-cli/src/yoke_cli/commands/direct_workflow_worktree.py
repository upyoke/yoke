"""Client adapters for engine-owned worktree preparation and path resolution."""

from __future__ import annotations

import subprocess
import sys
from yoke_cli.commands._helpers import show_delegate_help
from typing import Callable, Dict, List, Tuple

from yoke_cli.commands._helpers import client_project_context
from yoke_contracts.public_ref import parse_public_item_ref

AdapterFn = Callable[[List[str]], int]
PREPARE_USAGE = (
    "yoke direct-workflow worktree prepare ITEM --workflow dash|blitz "
    "[--project P] [--session-id S] [--json]"
)


def direct_workflow_worktree_prepare(args: List[str]) -> int:
    """Delegate local engine mutation without importing engine authority."""
    if show_delegate_help(
        args,
        PREPARE_USAGE,
        "Requires the item work claim; prepares its registered lane from verified upstream.",
    ):
        return 0
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


WORKTREE_PREPARE_USAGE = "yoke worktree prepare --item PREFIX-N [--project P]"
WORKTREE_PATHS_USAGE = "yoke worktree paths main"


def worktree_prepare(args: List[str]) -> int:
    """Use the running Yoke interpreter before any claimed lane exists."""
    if show_delegate_help(
        args,
        WORKTREE_PREPARE_USAGE,
        "Requires the item work claim; creates/reuses every registered task and "
        "integration lane from the item's mapped main checkout. Refusals name "
        "the failed claim, path, upstream or lane check; repair it and rerun.",
    ):
        return 0
    return subprocess.run(
        [sys.executable, "-m", "yoke_core.domain.worktree_preflight", *args],
        check=False,
    ).returncode


def worktree_paths(args: List[str]) -> int:
    """Resolve paths on the installed runtime, without a source lane."""
    if show_delegate_help(
        args,
        WORKTREE_PATHS_USAGE,
        "Resolve the registered main checkout before task lanes exist. "
        "Run from the owning project checkout; preparation resolves the "
        "item's own project mapping independently.",
    ):
        return 0
    return subprocess.run(
        [sys.executable, "-m", "yoke_core.domain.worktree", "paths", *args],
        check=False,
    ).returncode


TOOL_SHAPED_SUBCOMMANDS: Dict[Tuple[str, ...], AdapterFn] = {
    ("direct-workflow", "worktree", "prepare"): (direct_workflow_worktree_prepare),
    ("worktree", "prepare"): worktree_prepare,
    ("worktree", "paths"): worktree_paths,
}
TOOL_SHAPED_USAGE = {
    "yoke direct-workflow worktree prepare": PREPARE_USAGE,
    "yoke worktree prepare": WORKTREE_PREPARE_USAGE,
    "yoke worktree paths": WORKTREE_PATHS_USAGE,
}


__all__ = [
    "PREPARE_USAGE",
    "TOOL_SHAPED_SUBCOMMANDS",
    "TOOL_SHAPED_USAGE",
    "direct_workflow_worktree_prepare",
]
