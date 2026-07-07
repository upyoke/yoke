"""Client-side checkout context helpers."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Optional


def resolve_repo_root_from_cwd(cwd: str | None = None) -> Optional[str]:
    """Return the owning main repo root for the caller's cwd, if any."""

    selected = cwd or os.environ.get("YOKE_RESOLVE_CWD") or os.getcwd()
    root = _git_toplevel(selected)
    if root is None:
        return None
    return _strip_worktree_path(root)


def _git_toplevel(cwd: str) -> Optional[str]:
    try:
        result = subprocess.run(
            ["git", "-C", cwd, "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def _strip_worktree_path(path: str) -> str:
    candidate = str(Path(path).expanduser())
    markers = ("/" + ".worktrees/", "/" + ".claude/worktrees/")
    for marker in markers:
        if marker in candidate:
            return candidate.split(marker, 1)[0]
    return candidate


__all__ = ["resolve_repo_root_from_cwd"]
