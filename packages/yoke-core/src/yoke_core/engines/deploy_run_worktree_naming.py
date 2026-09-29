"""How a self-deploy run's pinned driver worktree is named, and how to find one.

A self-deploy run freezes its source in a detached worktree so the driver reads
a tree a merge landing on the live checkout cannot move underneath it. Two
unrelated places need to agree about where that directory is: the pinning path
that creates it, and the retirement path that reclaims it once the run is over.
They agree by both asking here, because a prefix spelled twice is a sweep that
silently stops finding what the creator still makes.

Recognition is by path shape alone — directly under this checkout's
``.worktrees``, carrying the driver prefix — so it needs no database and works
on a directory whose run no longer exists anywhere.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable


DRIVER_WORKTREE_PREFIX = "deploy-"
WORKTREES_DIR_NAME = ".worktrees"


def driver_worktree_name(run_id: str) -> str:
    """The directory name a run's pinned driver source lives under."""
    return f"{DRIVER_WORKTREE_PREFIX}{run_id}"


def driver_worktree_path(checkout: Path, run_id: str) -> Path:
    """Where *run_id* pins its self-deploy driver source inside *checkout*."""
    return checkout / WORKTREES_DIR_NAME / driver_worktree_name(run_id)


def run_id_for_driver_worktree(path: Path, repo_root: Path) -> str:
    """The run id *path* pins for, or ``""`` when it is not a driver worktree.

    An item lane named after an item, a nested directory inside a driver tree,
    and a path somewhere else entirely all read as "not mine".
    """
    if path.parent != repo_root / WORKTREES_DIR_NAME:
        return ""
    if not path.name.startswith(DRIVER_WORKTREE_PREFIX):
        return ""
    return path.name[len(DRIVER_WORKTREE_PREFIX) :]


def deploy_run_worktree_paths(
    run_git: Callable[..., Any], repo_root: str | Path
) -> list[Path] | None:
    """Every driver worktree git registers here, or ``None`` when it cannot say.

    Read straight from ``git worktree list`` rather than through the
    branch-bearing registry in ``git_worktree_registry``, because a driver
    worktree is detached by design and that registry drops it — which is why
    the lane-retirement paths built on it never saw one.
    """
    root = Path(repo_root).resolve()
    result = run_git(["worktree", "list", "--porcelain"], cwd=str(root), capture=True)
    if result.returncode != 0:
        return None
    found: list[Path] = []
    for line in (result.stdout or "").splitlines():
        if not line.startswith("worktree "):
            continue
        path = Path(line.removeprefix("worktree ")).resolve()
        if run_id_for_driver_worktree(path, root):
            found.append(path)
    return found


__all__ = [
    "DRIVER_WORKTREE_PREFIX",
    "WORKTREES_DIR_NAME",
    "deploy_run_worktree_paths",
    "driver_worktree_name",
    "driver_worktree_path",
    "run_id_for_driver_worktree",
]
