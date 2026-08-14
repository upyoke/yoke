"""Purge stale bytecode from a lane so its imports match a clean checkout.

A long-lived worktree accumulates ``__pycache__`` entries whose recorded
source mtime still matches a file that has since been rewritten. A fresh
interpreter then loads the old body, while a clean checkout of the same
commit compiles current source and disagrees. Merge-time cache removal
only runs when the lane is being destroyed; preparation reuses the lane
and must drop that bytecode before tests run.
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from yoke_core.domain.worktree_test_environment import PROOF_DIRECTORY_NAME

_SKIP_DESCEND = frozenset(
    {".git", ".venv", ".worktrees", "build", "dist", "node_modules"}
)
_PURGE_DIR_NAMES = frozenset(
    {"__pycache__", ".pytest_cache", PROOF_DIRECTORY_NAME}
)
_PURGE_SUFFIXES = (".pyc", ".pyo")


@dataclass(frozen=True)
class LaneHygieneReport:
    """What bytecode hygiene removed from a lane."""

    purged_paths: tuple[str, ...] = ()
    error: str = ""

    @property
    def actions(self) -> tuple[str, ...]:
        if not self.purged_paths:
            return ()
        return (f"purged-bytecode={len(self.purged_paths)}",)


def purge_lane_bytecode_caches(
    worktree_path: str | Path,
) -> LaneHygieneReport:
    """Remove bytecode and pytest caches, leaving source and the venv intact."""
    root = Path(worktree_path).resolve()
    if not root.is_dir():
        return LaneHygieneReport()
    purged: list[str] = []
    try:
        for dirpath, dirnames, filenames in os.walk(root, topdown=True):
            here = Path(dirpath)
            dirnames[:] = [name for name in dirnames if name not in _SKIP_DESCEND]
            for name in tuple(dirnames):
                if name not in _PURGE_DIR_NAMES:
                    continue
                target = here / name
                shutil.rmtree(target)
                purged.append(str(target.relative_to(root)))
                dirnames.remove(name)
            for name in filenames:
                if not name.endswith(_PURGE_SUFFIXES):
                    continue
                target = here / name
                target.unlink()
                purged.append(str(target.relative_to(root)))
    except OSError as exc:
        return LaneHygieneReport(tuple(purged), error=str(exc))
    return LaneHygieneReport(tuple(purged))


__all__ = ["LaneHygieneReport", "purge_lane_bytecode_caches"]
