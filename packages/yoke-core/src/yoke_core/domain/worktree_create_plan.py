"""Worktree planning helpers for ``create_worktree``.

Houses the multi-worktree vocabulary the unified creator uses to handle both
single-worktree issue items and multi-worktree epic items through one
provisioning loop. Single-worktree is the N=1 case; multi-worktree epics
resolve their worktree list from ``epic_dispatch_chains``.

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

from yoke_core.domain import db_backend
from yoke_core.domain.schema_common import _table_exists


@dataclass
class WorktreeCreationEntry:
    """One worktree in a multi-worktree ``create_worktree`` call.

    A single-worktree issue resolves to one entry; an epic resolves to one
    entry per ``epic_dispatch_chains`` row.
    """

    branch: str
    path: str
    created: bool = False
    preexisting: bool = False
    error: Optional[str] = None


@dataclass
class WorktreeCreationPlan:
    """All-worktree preflight result.

    ``worktrees`` is ordered to match the underlying source —
    single-worktree fallback first, then ``epic_dispatch_chains.worktree``
    ordering for epic items. ``primary`` is the first worktree; the
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


def _worktree_tuple(branch: str, path: str, repo_root: str, wt_dir: str) -> Tuple[str, str]:
    branch = (branch or "").strip()
    path = (path or "").strip()
    if not path and branch:
        path = os.path.join(repo_root, wt_dir, branch)
    if not branch and path:
        branch = os.path.basename(path)
    if path and not os.path.isabs(path):
        path = os.path.join(repo_root, path)
    return branch, path


def resolve_worktrees_for_item(
    item_id: int,
    repo_root: str,
    wt_dir: str,
    db_path: Optional[str] = None,
) -> List[Tuple[str, str]]:
    """Return ``(branch, path)`` worktree pairs for ``item_id``.

    Issue / unknown / no-DB items resolve to one worktree keyed on
    ``YOK-N``. Epic items read their worktree list from
    ``epic_dispatch_chains``; when that table is empty for the epic, the
    resolver falls back to the single-worktree shape so the caller never
    produces a partial epic.
    """
    fallback = [(f"YOK-{item_id}", os.path.join(repo_root, wt_dir, f"YOK-{item_id}"))]

    try:
        from yoke_core.domain.db_helpers import connect
    except Exception:
        return fallback

    if not db_path:
        return fallback

    try:
        conn = connect(db_path)
    except Exception:
        return fallback

    try:
        if not _table_exists(conn, "items"):
            return fallback
        p = "%s" if db_backend.connection_is_postgres(conn) else "?"
        row = conn.execute(
            f"SELECT type FROM items WHERE id = {p}", (int(item_id),),
        ).fetchone()
        item_type = (row["type"] or "issue") if row else "issue"
        if item_type != "epic":
            return fallback
        if not _table_exists(conn, "epic_dispatch_chains"):
            return fallback

        rows = conn.execute(
            """SELECT COALESCE(worktree, '') AS branch,
                      COALESCE(worktree_path, '') AS path
               FROM epic_dispatch_chains
               WHERE epic_id = {p}
                 AND COALESCE(worktree, '') <> ''
               ORDER BY worktree""".format(p=p),
            (int(item_id),),
        ).fetchall()

        worktrees = [
            _worktree_tuple(row["branch"], row["path"], repo_root, wt_dir)
            for row in rows
        ]
        return worktrees or fallback
    finally:
        conn.close()


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
    raw_worktrees: Sequence[Tuple[str, str]],
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
    for branch, path in raw_worktrees:
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

        entry = WorktreeCreationEntry(branch=branch, path=path)
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
    dirty = sorted({
        p.strip()
        for p in (tracked.stdout + "\n" + staged.stdout).splitlines()
        if p.strip()
    })
    if dirty:
        return (
            "Cannot create worktree: main has tracked or staged changes. "
            "Commit, stash, or revert them and retry. Dirty paths: "
            + ", ".join(dirty[:20])
        )
    untracked_run = _run([
        "git", "-C", repo_root, "ls-files", "--others", "--exclude-standard",
    ])
    worktrees_rel = os.path.relpath(worktrees_dir, repo_root).rstrip("/")
    untracked = [
        p.strip() for p in untracked_run.stdout.splitlines()
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
