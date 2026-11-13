"""The one rule every lane retirement path applies to a lane's contents.

A finished lane holds work only when git reports it: a change to a tracked
file, or an untracked file the checkout's ignore rules do not cover. Every
ignored file is disposable — build output, caches, virtualenvs and the
operating-layer state Yoke renders into each checkout alike — and leaves with
the tree when :func:`yoke_core.engines.worktree_removal.remove_worktree`
deletes its tombstone. The status read therefore never asks git for ignored
content, which also keeps it cheap once a machine holds many lanes.

Landing cleanup, the machine-wide merged-lane sweep, deploy-run driver
retirement and the doctor lane report all read this one classification, so a
lane is never disposable to one of them and precious to another.

One shape is neither work nor empty: a tree whose only changes are deleted
tracked files. That is what an interrupted ``git worktree remove`` leaves
behind — git deletes tracked files and drops its admin record last — so the
assessment names it ``interrupted_removal``. A caller that has also proved the
branch landed completes that removal: every deleted file is in the landed
commits.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


@dataclass(frozen=True)
class LaneResidueAssessment:
    """Read-only classification of everything git reports in a lane."""

    disposable: bool
    precious_paths: tuple[str, ...] = ()
    reason: str = ""
    interrupted_removal: bool = False

    @property
    def removable_once_landed(self) -> bool:
        """Disposable, or an interrupted removal a landed branch may finish."""
        return self.disposable or self.interrupted_removal


def _status(run_git: Callable[..., Any], path: Path) -> Any:
    # ``normal`` reports an untracked directory as one line; the verdict only
    # needs to know that something non-ignored exists there.
    return run_git(
        ["-C", str(path), "status", "--porcelain", "--untracked-files=normal"],
        cwd=str(path),
        capture=True,
    )


def _kept(reason: str, precious_paths: tuple[str, ...] = ()) -> LaneResidueAssessment:
    return LaneResidueAssessment(False, precious_paths=precious_paths, reason=reason)


def assess_lane_residue(
    run_git: Callable[..., Any], worktree_path: str | Path
) -> LaneResidueAssessment:
    """Classify a lane without changing it.

    Disposable means git reports no tracked change and no untracked,
    non-ignored file, and the lane does not hold the interpreter running the
    cleanup.
    """
    root = Path(worktree_path).resolve()
    current = _status(run_git, root)
    if current.returncode != 0:
        return _kept("worktree status unreadable")

    precious: list[str] = []
    deleted = 0
    for line in (current.stdout or "").splitlines():
        if not line.strip():
            continue
        precious.append(line[3:] if len(line) > 3 else line)
        deleted += line.startswith(" D ")
    if precious and deleted == len(precious):
        return LaneResidueAssessment(
            False,
            precious_paths=tuple(precious),
            reason=(
                f"interrupted removal: {deleted} tracked file"
                f"{'s' if deleted != 1 else ''} already deleted, nothing else changed"
            ),
            interrupted_removal=True,
        )
    if precious:
        return _kept(
            "unignored changes present: " + ", ".join(precious), tuple(precious)
        )
    executable = Path(sys.executable).resolve()
    if executable.is_relative_to(root):
        return _kept("the lane contains the active interpreter")
    return LaneResidueAssessment(True)


__all__ = [
    "LaneResidueAssessment",
    "assess_lane_residue",
]
