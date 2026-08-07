"""Same-tree QA coverage check for the merge-time verification gate.

The merge boundary re-executes the project's registered verification command
against the rebased candidate so an integrated tree never lands unproven.
When the rebase was a no-op, that tree is byte-identical to the tree a
passing QA case run already covered, and re-running the suite is pure
duplication. This module answers "does recorded QA evidence already cover
this exact tree?" by comparing git tree object ids — commit shas differ
across a rebase, tree ids do not.

Every uncertainty (no evidence, unknown sha, unreadable repository) returns
``None`` so the gate falls back to executing the suite.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any, Optional


def _tree_object_id(worktree: str | Path, rev: str) -> Optional[str]:
    """Resolve *rev* to its git tree object id inside *worktree*, or None."""
    try:
        proc = subprocess.run(
            [
                "git", "-C", str(worktree),
                "rev-parse", "--verify", "--quiet", f"{rev}^{{tree}}",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout.strip() or None


def covering_run_receipt(
    worktree: str | Path,
    covering_runs: list[dict[str, Any]],
) -> Optional[str]:
    """Return a receipt line when passing QA evidence covers HEAD's tree.

    ``covering_runs`` entries carry ``run_id`` and ``head_sha`` (the exact
    commit a passing QA run tested). A run covers the candidate when that
    commit's tree object id equals HEAD's tree object id in *worktree*. A
    head commit the local repository does not contain, or any git failure,
    simply disqualifies that entry — the caller then runs the suite.
    """
    candidate_tree = _tree_object_id(worktree, "HEAD")
    if candidate_tree is None:
        return None
    for run in covering_runs or []:
        if not isinstance(run, dict):
            continue
        head_sha = str(run.get("head_sha") or "").strip()
        if not head_sha:
            continue
        covered_tree = _tree_object_id(worktree, head_sha)
        if covered_tree is not None and covered_tree == candidate_tree:
            return (
                "[phase:tests] skipping registered verification: passing QA "
                f"run {run.get('run_id')} already covered identical tree "
                f"{candidate_tree[:12]} (head {head_sha[:12]})"
            )
    return None


__all__ = ["covering_run_receipt"]
