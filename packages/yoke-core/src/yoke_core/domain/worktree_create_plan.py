"""Worktree planning helpers for ``create_worktree``.

Houses the multi-worktree vocabulary the unified creator uses to handle both
single-lane and task-lane items through one provisioning loop.

Why this module exists: ``worktree_create.py`` already approaches the
350-line hard limit owned by ``yoke_core.domain.file_line_check``.
Worktree planning, idempotency classification, and capacity preflight live
here so the orchestrator stays small and the creator's per-worktree
provisioning loop reads top-to-bottom.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import List, Optional, Sequence, Tuple

from yoke_core.domain.workflow_behavior import LANE_IMPLEMENTATION
from yoke_core.domain.worktree_lane_plan import (
    resolve_worktree_lanes_for_item,
)


@dataclass
class WorktreeCreationEntry:
    """One worktree in a multi-worktree ``create_worktree`` call.

    Every entry is backed by the item's universal lane registry.
    """

    branch: str
    path: str
    lane_role: str = LANE_IMPLEMENTATION
    created: bool = False
    preexisting: bool = False
    error: Optional[str] = None


@dataclass
class WorktreeCreationPlan:
    """All-worktree preflight result.

    ``worktrees`` is ordered by universal lane priority. ``primary`` is the
    first worktree; the
    session's claim over it (not an envelope) defines write authority going
    forward.
    """

    worktrees: List[WorktreeCreationEntry] = field(default_factory=list)
    primary: Optional[WorktreeCreationEntry] = None
    error: Optional[str] = None
    failed_branch: str = ""

    @property
    def pending_worktree_count(self) -> int:
        return sum(1 for entry in self.worktrees if not entry.preexisting)


def resolve_worktrees_for_item(
    item_id: int,
    repo_root: str,
    wt_dir: str,
    db_path: Optional[str] = None,
) -> List[Tuple[str, str]]:
    """Return ``(branch, path)`` worktree pairs for ``item_id``.

    The compatibility return shape omits each lane role; all authority comes
    from ``item_worktrees`` through the shared workflow-policy resolver.
    """
    return [
        (branch, path)
        for branch, path, _lane_role in resolve_worktree_lanes_for_item(
            item_id,
            repo_root,
            wt_dir,
            db_path,
        )
    ]


def _classify_existing(branch: str, path: str) -> Tuple[bool, Optional[str]]:
    """Return ``(preexisting, error)`` for a worktree whose ``path`` exists.

    Idempotent re-entry returns ``(True, None)``. Mismatched state (not a
    git worktree, wrong branch checked out) returns ``(False, error)``.
    """
    from yoke_core.domain.worktree_paths import _run

    if not os.path.isdir(path):
        return False, None

    inside = _run(["git", "rev-parse", "--is-inside-work-tree"], cwd=path)
    if inside.returncode != 0 or inside.stdout.strip() != "true":
        return False, f"{path} exists but is not a git worktree"

    current = _run(["git", "branch", "--show-current"], cwd=path)
    if current.returncode == 0:
        live = current.stdout.strip()
        if live and live != branch:
            return False, (
                f"{path} exists on branch '{live}' but the planned worktree "
                f"declares branch '{branch}'"
            )
    return True, None


def preflight_worktree_plan(
    raw_worktrees: Sequence[Tuple[str, ...]],
    repo_root: str,
    worktrees_dir: str,
    max_active_worktrees: int,
    active_count: int,
    active_names: Sequence[str],
) -> WorktreeCreationPlan:
    """Validate the worktree plan all-at-once before any side effects.

    Detects duplicate paths, mismatched existing directories, and
    insufficient ``max_active_worktrees`` capacity (counting only the
    worktrees that need to be created).
    """
    plan = WorktreeCreationPlan()
    if not raw_worktrees:
        plan.error = "no worktrees resolved for item"
        return plan

    seen_paths: set = set()
    seen_branches: set = set()
    for raw in raw_worktrees:
        if len(raw) == 2:
            branch, path = raw
            lane_role = LANE_IMPLEMENTATION
        elif len(raw) == 3:
            branch, path, lane_role = raw
        else:
            plan.error = f"malformed worktree entry: {raw!r}"
            return plan
        if not branch or not path:
            plan.error = f"malformed worktree entry: branch='{branch}' path='{path}'"
            plan.failed_branch = branch or path
            return plan
        if path in seen_paths:
            plan.error = f"duplicate worktree path '{path}'"
            plan.failed_branch = branch
            return plan
        if branch in seen_branches:
            plan.error = f"duplicate worktree branch '{branch}'"
            plan.failed_branch = branch
            return plan
        seen_paths.add(path)
        seen_branches.add(branch)

        entry = WorktreeCreationEntry(
            branch=branch,
            path=path,
            lane_role=lane_role,
        )
        preexisting, err = _classify_existing(branch, path)
        if err:
            entry.error = err
            plan.worktrees.append(entry)
            plan.error = err
            plan.failed_branch = branch
            return plan
        entry.preexisting = preexisting
        plan.worktrees.append(entry)

    plan.primary = plan.worktrees[0]

    needed = plan.pending_worktree_count
    if needed and (active_count + needed) > max_active_worktrees:
        names = ", ".join(active_names)
        plan.error = (
            f"max_active_worktrees limit reached ({active_count} active "
            f"+ {needed} pending > {max_active_worktrees}). Merge existing "
            f"worktrees before creating more. Active worktrees: {names}"
        )
        return plan

    return plan


def dirty_main_error(repo_root: str, worktrees_dir: str) -> Optional[str]:
    """Return a dirty-main blocker message, or ``None`` when clean."""
    from yoke_core.domain.worktree_paths import _run

    tracked = _run(["git", "-C", repo_root, "diff", "--name-only"])
    staged = _run(["git", "-C", repo_root, "diff", "--name-only", "--cached"])
    dirty = sorted(
        {
            p.strip()
            for p in (tracked.stdout + "\n" + staged.stdout).splitlines()
            if p.strip()
        }
    )
    if dirty:
        return (
            "Cannot create worktree: main has tracked or staged changes. "
            "Commit, stash, or revert them and retry. Dirty paths: "
            + ", ".join(dirty[:20])
        )
    untracked_run = _run(
        [
            "git",
            "-C",
            repo_root,
            "ls-files",
            "--others",
            "--exclude-standard",
        ]
    )
    worktrees_rel = os.path.relpath(worktrees_dir, repo_root).rstrip("/")
    untracked = [
        p.strip()
        for p in untracked_run.stdout.splitlines()
        if p.strip()
        and p.strip() != "runtime/config"
        and not p.strip().startswith(worktrees_rel + "/")
    ]
    if untracked:
        return (
            "Cannot create worktree: main has untracked, non-gitignored files. "
            "Commit, remove, or gitignore them and retry. Untracked paths: "
            + ", ".join(untracked[:20])
        )
    return None


__all__ = [
    "WorktreeCreationEntry",
    "WorktreeCreationPlan",
    "dirty_main_error",
    "resolve_worktrees_for_item",
    "preflight_worktree_plan",
]
