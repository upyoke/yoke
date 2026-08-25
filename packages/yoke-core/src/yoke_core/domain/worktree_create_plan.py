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
    lane_id: Optional[int] = None
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
        for branch, path, *_rest in resolve_worktree_lanes_for_item(
            item_id,
            repo_root,
            wt_dir,
            db_path,
        )
    ]


def _classify_existing(branch: str, path: str) -> Tuple[bool, Optional[str]]:
    """Return ``(preexisting, error)`` for a worktree whose ``path`` exists.

    Idempotent re-entry returns ``(True, None)`` only for a healthy
    checkout. A leftover corrupt lane is repaired in place or refused.
    """
    from yoke_core.domain.worktree_reuse import classify_reusable_worktree

    return classify_reusable_worktree(branch, path)


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
            lane_id = None
        elif len(raw) == 3:
            branch, path, lane_role = raw
            lane_id = None
        elif len(raw) == 4:
            branch, path, lane_role, lane_id = raw
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
            lane_id=int(lane_id) if lane_id is not None else None,
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


def dirty_main_error(
    repo_root: str,
    worktrees_dir: str,
    needed_paths: Sequence[str] = (),
    source_root_prefixes: Sequence[str] = (),
) -> Optional[str]:
    """Return a dirty-main blocker, or ``None`` when creation may proceed."""
    from yoke_core.domain.worktree_dirty_main_guard import overlapping_dirty_main
    from yoke_core.domain.worktree_preflight_steps import BLOCK_DIRTY_TRACKED

    blocked, kind, paths = overlapping_dirty_main(
        repo_root,
        needed_paths=needed_paths,
        worktrees_dir=worktrees_dir,
        source_root_prefixes=source_root_prefixes,
    )
    if not blocked:
        return None
    listing = ", ".join(paths[:20])
    if kind == BLOCK_DIRTY_TRACKED:
        return (
            "Cannot create worktree: overlapping tracked or staged files on "
            "main match paths this lane needs. Dirty paths: " + listing
        )
    return (
        "Cannot create worktree: untracked files under source/package roots "
        "on main could collide with a new module. Dirty paths: " + listing
    )


__all__ = [
    "WorktreeCreationEntry",
    "WorktreeCreationPlan",
    "dirty_main_error",
    "resolve_worktrees_for_item",
    "preflight_worktree_plan",
]
