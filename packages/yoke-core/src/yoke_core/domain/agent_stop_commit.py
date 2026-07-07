"""SubagentStop safety-net auto-commit helper."""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass

from yoke_core.domain.db_helpers import BUSY_TIMEOUT_MS


@dataclass
class AutoCommitResult:
    """Result of auto-committing uncommitted worktree work."""

    committed: bool = False
    file_count: int = 0
    files: str = ""


def auto_commit_worktree(worktree_path: str, item_label: str) -> AutoCommitResult:
    """Auto-commit uncommitted work in a worktree directory.

    This is a crash-recovery safety net. The parent conduct must treat any
    safety-net auto-commit as a failed submission and re-dispatch.

    Args:
        worktree_path: Absolute path to the worktree.
        item_label: Label for the commit.

    Returns:
        AutoCommitResult with commit details.
    """
    if not worktree_path or not os.path.isdir(worktree_path):
        return AutoCommitResult()

    # Guard: must be a git directory.
    try:
        r = subprocess.run(
            ["git", "-C", worktree_path, "rev-parse", "--git-dir"],
            capture_output=True,
            timeout=5,
        )
        if r.returncode != 0:
            return AutoCommitResult()
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return AutoCommitResult()

    # Check for uncommitted changes. Parser note: ``git status --porcelain``
    # v1 format is ``XY filename``. Do NOT strip() the raw stdout before
    # splitting — that eats the leading space of the first line and corrupts
    # ``l[3:]`` filename extraction for space-prefixed statuses
    # (``' M README.md'`` → ``'M README.md'`` → ``l[3:] == 'EADME.md'``).
    # Strip only the trailing newline and filter empty lines manually.
    try:
        r = subprocess.run(
            ["git", "-C", worktree_path, "status", "--porcelain"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        dirty = r.stdout.rstrip("\n")
        if not dirty:
            return AutoCommitResult()
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return AutoCommitResult()

    lines = [l for l in dirty.splitlines() if l.strip()]
    file_count = len(lines)
    files = ", ".join(l[3:] for l in lines if len(l) > 3)

    try:
        subprocess.run(
            ["git", "-C", worktree_path, "add", "-A"],
            capture_output=True,
            timeout=10,
        )
        r = subprocess.run(
            ["git", "-C", worktree_path, "diff", "--cached", "--quiet"],
            capture_output=True,
            timeout=5,
        )
        if r.returncode == 0:
            return AutoCommitResult()

        subprocess.run(
            [
                "git",
                "-C",
                worktree_path,
                "commit",
                "-m",
                f"chore: auto-commit Engineer uncommitted work [{item_label}] (SubagentStop safety net)",
            ],
            capture_output=True,
            timeout=10,
        )
        return AutoCommitResult(committed=True, file_count=file_count, files=files)
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return AutoCommitResult()
