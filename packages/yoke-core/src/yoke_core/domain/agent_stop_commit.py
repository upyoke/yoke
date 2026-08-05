"""SubagentStop safety-net auto-commit helper."""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass



@dataclass
class AutoCommitResult:
    """Result of auto-committing uncommitted worktree work.

    ``pre_staged`` is non-empty when the index already carried entries
    this agent did not stage. Nothing is committed in that case: the
    caller surfaces the paths so their author can be found, because a
    shared worktree index means they may belong to a different session
    entirely.
    """

    committed: bool = False
    file_count: int = 0
    files: str = ""
    pre_staged: tuple[str, ...] = ()


def _staged_paths(worktree_path: str) -> tuple[str, ...]:
    """Paths already in the index, or ``()`` when git cannot be asked."""
    try:
        r = subprocess.run(
            ["git", "-C", worktree_path, "diff", "--cached", "--name-only"],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return ()
    if r.returncode != 0:
        return ()
    return tuple(
        line for line in r.stdout.rstrip("\n").splitlines() if line.strip()
    )


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

    lines = [entry for entry in dirty.splitlines() if entry.strip()]
    file_count = len(lines)
    files = ", ".join(entry[3:] for entry in lines if len(entry) > 3)

    # This net exists to preserve THIS agent's uncommitted work. Entries
    # already in the index were staged by something else — a worktree's
    # index is shared by every process in it — and `add -A` followed by a
    # bare commit would sweep them into a commit nobody authored.
    pre_staged = _staged_paths(worktree_path)
    if pre_staged:
        return AutoCommitResult(pre_staged=pre_staged)

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
