"""Validate and repair a worktree before ``create_worktree`` reuses it."""

from __future__ import annotations

import os
import subprocess
from typing import List, Optional, Tuple

from yoke_core.domain.worktree_paths import _run, captured_process_detail

_RESTORE_CHUNK = 64
_RESTORE_TIMEOUT_SECONDS = 120


def classify_reusable_worktree(
    branch: str,
    path: str,
) -> Tuple[bool, Optional[str]]:
    """Return ``(preexisting, error)`` for a path that may already be a lane.

    Reuse requires a non-null path, an intact HEAD, and a non-empty index.
    A corrupt leftover is repaired with ``git reset`` plus restore of only
    git-reported-missing paths; if repair cannot make the checkout healthy,
    the caller must refuse rather than hand the lane back as reused.
    """
    if not (path or "").strip():
        return False, "recorded worktree path is null"
    if not os.path.isdir(path):
        return False, None

    inside = _run(["git", "rev-parse", "--is-inside-work-tree"], cwd=path)
    if inside.returncode != 0 or inside.stdout.strip() != "true":
        return False, f"{path} exists but is not a git worktree"

    current = _run(["git", "branch", "--show-current"], cwd=path)
    if current.returncode == 0:
        live = current.stdout.strip()
        if live and live != branch:
            return False, (
                f"{path} exists on branch '{live}' but the planned worktree "
                f"declares branch '{branch}'"
            )

    problem = inspect_worktree_checkout(path)
    if problem is None:
        return True, None
    repair_err = repair_worktree_checkout(path)
    if repair_err:
        return False, (
            f"{path} is not reusable ({problem}); repair failed: {repair_err}"
        )
    return True, None


def inspect_worktree_checkout(path: str) -> Optional[str]:
    """Return a problem description, or ``None`` when the checkout is healthy."""
    head = _git(path, "rev-parse", "--verify", "HEAD")
    if head.returncode != 0:
        return f"{path} has no intact HEAD checkout"
    indexed = _git(path, "ls-files")
    if indexed.returncode != 0:
        return f"{path} could not read the index: {captured_process_detail(indexed)}"
    if not indexed.stdout.strip():
        return f"{path} has an empty index"
    missing = _missing_paths(path)
    if missing is None:
        return f"{path} could not list missing files"
    if missing:
        return f"{path} is missing {len(missing)} tracked path(s)"
    return None


def repair_worktree_checkout(path: str) -> Optional[str]:
    """Rebuild the index from HEAD, then restore git-reported-missing paths."""
    reset = _git(path, "reset")
    if reset.returncode != 0:
        return f"git reset failed: {captured_process_detail(reset)}"
    missing = _missing_paths(path)
    if missing is None:
        return "could not list missing files after reset"
    for offset in range(0, len(missing), _RESTORE_CHUNK):
        chunk = missing[offset : offset + _RESTORE_CHUNK]
        restored = _git(
            path,
            "restore",
            "--source=HEAD",
            "--worktree",
            "--",
            *chunk,
            timeout=_RESTORE_TIMEOUT_SECONDS,
        )
        if restored.returncode != 0:
            return (
                "git restore of missing paths failed: "
                f"{captured_process_detail(restored)}"
            )
    return inspect_worktree_checkout(path)


def _missing_paths(path: str) -> Optional[List[str]]:
    listed = _git(path, "ls-files", "-d")
    if listed.returncode != 0:
        return None
    return [line for line in listed.stdout.splitlines() if line.strip()]


def _git(
    path: str,
    *args: str,
    timeout: int = 30,
) -> subprocess.CompletedProcess:
    return _run(["git", "-C", path, *args], timeout=timeout)


__all__ = [
    "classify_reusable_worktree",
    "inspect_worktree_checkout",
    "repair_worktree_checkout",
]
