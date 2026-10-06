"""Machine-local, best-effort Git enrichment for conflict surveys."""

from __future__ import annotations

import subprocess
from pathlib import Path


def _git_lines(worktree_path: str, argv: list[str]) -> list[str]:
    try:
        result = subprocess.run(
            ["git", "-C", worktree_path, *argv],
            check=False,
            capture_output=True,
            text=True,
            timeout=3,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    if result.returncode != 0:
        return []
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def git_touched_paths(worktree_path: str, integration_target: str) -> list[str]:
    """Return changed paths from a live worktree when git can read it.

    Three reads, because committed history alone hides an agent that is
    mid-edit: the branch's own commits against the integration target,
    tracked edits not yet committed, and files git is not tracking yet.
    Ignored files stay out, so lane scratch never reads as declared work.
    """
    try:
        if not worktree_path or not Path(worktree_path).is_dir():
            return []
    except OSError:
        return []
    touched: list[str] = []
    for argv in (
        ["diff", "--name-only", f"{integration_target}...HEAD"],
        ["diff", "--name-only", "HEAD"],
        ["ls-files", "--others", "--exclude-standard"],
    ):
        touched.extend(_git_lines(worktree_path, argv))
    return list(dict.fromkeys(touched))
