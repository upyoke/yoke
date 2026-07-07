"""Source-side Git IO wrapper for effective staged-set calculation."""

from __future__ import annotations

import subprocess
from typing import Optional

from yoke_contracts.hook_runner.main_commit import (
    EffectiveStagedSet,
    effective_staged_set as _effective_staged_set,
)


__all__ = ["EffectiveStagedSet", "effective_staged_set", "worktree_blob"]


def worktree_blob(path: str) -> Optional[str]:
    """Return the worktree content of *path*, or ``None`` when unreadable."""
    try:
        with open(path, encoding="utf-8", errors="replace") as handle:
            return handle.read()
    except OSError:
        return None


def _modified_and_untracked() -> Optional[list[str]]:
    """All modified + untracked paths (``git status --porcelain -z``)."""
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain", "-z"],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except Exception:
        return None
    if result.returncode != 0:
        return None
    paths: list[str] = []
    entries = iter(result.stdout.split("\0"))
    for entry in entries:
        if len(entry) < 4 or entry[2] != " ":
            continue
        status, path = entry[:2], entry[3:]
        if path:
            paths.append(path)
        if "R" in status or "C" in status:
            next(entries, None)
    return paths


def effective_staged_set(
    command: str, staged: Optional[list[str]],
) -> Optional[EffectiveStagedSet]:
    """Union *staged* with same-command add-derived targets."""
    return _effective_staged_set(
        command,
        staged,
        modified_and_untracked=_modified_and_untracked(),
    )
