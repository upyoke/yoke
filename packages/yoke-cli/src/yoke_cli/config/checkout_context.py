"""Client-side checkout context helpers."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Optional
from yoke_contracts import terminal_detached_process


def resolve_repo_root_from_cwd(cwd: str | None = None) -> Optional[str]:
    """Return the owning main repo root for the caller's cwd, if any."""

    selected = cwd or os.environ.get("YOKE_RESOLVE_CWD") or os.getcwd()
    root = _git_toplevel(selected)
    if root is None:
        return None
    return _strip_worktree_path(root)


def _git_toplevel(cwd: str) -> Optional[str]:
    try:
        result = terminal_detached_process.run(
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
    # Match path components, not "/"-joined text: Windows renders a Git
    # toplevel such as C:/repo/.worktrees/lane with backslash separators.
    candidate = Path(path).expanduser()
    parts = candidate.parts
    for marker in ((".worktrees",), (".claude", "worktrees")):
        width = len(marker)
        # The marker must sit below the root and above a lane name.
        for start in range(1, len(parts) - width):
            if parts[start : start + width] == marker:
                return str(Path(*parts[:start]))
    return str(candidate)


__all__ = ["resolve_repo_root_from_cwd"]
