"""Removing a lane directory so no interruption can strand it half-deleted.

``git worktree remove`` deletes the tree file by file and drops git's admin
record last. A doctor ``--fix`` run killed by its check budget mid-removal once
left a registered worktree with thousands of tracked files gone, which every
later residue read preserved as dirty work. Removal here is three resumable
steps instead: rename the directory to a tombstone on the same filesystem (one
atomic step), ``git worktree prune`` the now-missing registration, then delete
the tombstone. An interruption after the rename leaves only a tombstone, which
any later sweep finishes through :func:`finish_tombstones`.

A removal runs to completion once started: it is not bounded by a caller's
shrinking check deadline, and its git step has its own fixed timeout. A
doctor check starts one only while enough budget remains, and otherwise
defers it to the next run with the reason named.
"""

from __future__ import annotations

import shutil
import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path

from yoke_contracts.doctor_budget import pause_check_budget, remaining_budget

TOMBSTONE_PREFIX = ".removing-"
# git steps are bounded on their own clock, never the caller's deadline.
GIT_TIMEOUT_S = 60.0
# A doctor check starts a removal only with at least this much budget left.
REMOVAL_MIN_BUDGET_S = 10.0
_MANAGED_ROOTS = (Path(".worktrees"), Path(".claude") / "worktrees")


@dataclass(frozen=True)
class WorktreeRemoval:
    """Whether a worktree is gone from git; ``reason`` names what remains."""

    removed: bool
    reason: str = ""


def removal_deferral() -> str:
    """Why a removal must wait for a later run; empty when it may start now."""
    remaining = remaining_budget()
    if remaining is None or remaining >= REMOVAL_MIN_BUDGET_S:
        return ""
    return (
        f"removal deferred: {max(remaining, 0):.0f}s of the check budget remain "
        f"and a removal runs to completion once started (needs "
        f"{REMOVAL_MIN_BUDGET_S:.0f}s); rerun with --fix to retire it"
    )


def remove_worktree(
    repo_root: str | Path, worktree_path: str | Path
) -> WorktreeRemoval:
    """Retire one proved-disposable worktree through a tombstone."""
    deferred = removal_deferral()
    if deferred:
        return WorktreeRemoval(False, deferred)
    with pause_check_budget():
        return _remove(Path(repo_root), Path(worktree_path))


def tombstones(repo_root: str | Path) -> list[Path]:
    """Tombstones an interrupted removal left under the managed lane roots."""
    found: list[Path] = []
    for managed in _MANAGED_ROOTS:
        root = Path(repo_root) / managed
        if root.is_dir():
            found.extend(
                sorted(
                    child
                    for child in root.iterdir()
                    if child.name.startswith(TOMBSTONE_PREFIX) and child.is_dir()
                )
            )
    return found


def finish_tombstones(repo_root: str | Path) -> list[WorktreeRemoval]:
    """Complete every interrupted removal; one result per tombstone found."""
    leftovers = tombstones(repo_root)
    if not leftovers:
        return []
    with pause_check_budget():
        return _finish(Path(repo_root), leftovers)


def _tombstone_home(repo_root: Path, path: Path) -> Path:
    """The managed root holding ``path``, where the sweep looks for tombstones."""
    for managed in _MANAGED_ROOTS:
        root = repo_root / managed
        if path.is_relative_to(root):
            return root
    return path.parent


def _remove(repo_root: Path, path: Path) -> WorktreeRemoval:
    admin = _admin_dir(path)
    if admin is None or not admin.is_dir():
        return WorktreeRemoval(False, f"{path} is not a worktree git registers")
    lock = admin / "locked"
    if lock.exists():
        # git worktree prune keeps a locked registration, so the tree stays.
        note = lock.read_text(encoding="utf-8", errors="replace").strip()
        return WorktreeRemoval(
            False, f"worktree is locked ({note or 'no reason recorded'})"
        )
    name = f"{TOMBSTONE_PREFIX}{path.name}-{uuid.uuid4().hex[:8]}"
    tombstone = _tombstone_home(repo_root.resolve(), path.resolve()) / name
    try:
        path.rename(tombstone)
    except OSError as exc:
        return WorktreeRemoval(False, f"worktree rename refused for {path}: {exc}")
    [result] = _finish(repo_root, [tombstone])
    if result.removed:
        _remove_empty_parent(path.parent)
    return result


def _admin_dir(tree: Path) -> Path | None:
    """Git's record for a linked worktree, read from its ``.git`` link file."""
    try:
        link = (tree / ".git").read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if not link.startswith("gitdir: "):
        return None
    admin = Path(link.removeprefix("gitdir: "))
    return admin if admin.is_absolute() else (tree / admin).resolve()


def _finish(repo_root: Path, leftovers: list[Path]) -> list[WorktreeRemoval]:
    pruned = _git(repo_root, "worktree", "prune")
    if isinstance(pruned, str):
        return [
            WorktreeRemoval(
                False, f"{pruned}; tombstone {leftover} is kept for the next sweep"
            )
            for leftover in leftovers
        ]
    results = []
    for leftover in leftovers:
        admin = _admin_dir(leftover)
        if admin is not None and admin.is_dir():
            # Git still records this tree (a lock survives prune): keep it.
            results.append(
                WorktreeRemoval(
                    False,
                    f"git still registers tombstone {leftover}; it is kept for "
                    "an operator to unlock or restore",
                )
            )
            continue
        try:
            shutil.rmtree(leftover)
        except OSError as exc:
            # Git no longer registers it; only the inert tombstone remains.
            results.append(
                WorktreeRemoval(True, f"tombstone {leftover} not yet deleted: {exc}")
            )
        else:
            results.append(WorktreeRemoval(True))
    return results


def _git(repo_root: Path, *args: str) -> str | bytes:
    """Run git on its own fixed clock: stdout as bytes, or why it failed as str."""
    command = ["git", "-C", str(repo_root), *args]
    try:
        result = subprocess.run(command, capture_output=True, timeout=GIT_TIMEOUT_S)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f"git {' '.join(args)} failed: {exc}"
    if result.returncode != 0:
        detail = result.stderr.decode(errors="replace").strip().splitlines()
        return f"git {' '.join(args)} failed: " + (
            detail[0] if detail else f"exit {result.returncode}"
        )
    return result.stdout


def _remove_empty_parent(parent: Path) -> None:
    if parent.name in (".worktrees", "worktrees") or "/.worktrees/" not in f"{parent}/":
        return
    try:
        if not any(parent.iterdir()):
            parent.rmdir()
    except OSError:
        pass


__all__ = [
    "REMOVAL_MIN_BUDGET_S",
    "TOMBSTONE_PREFIX",
    "WorktreeRemoval",
    "finish_tombstones",
    "remove_worktree",
    "removal_deferral",
    "tombstones",
]
