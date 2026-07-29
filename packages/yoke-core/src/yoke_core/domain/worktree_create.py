"""Worktree creation surface.

Owns ``create_worktree`` and its per-worktree provisioning loop. A
single-worktree workflow is the N=1 case of a multi-lane workflow — the
creator resolves universal item lanes and runs one provisioning
path covering both shapes. Worktree planning, idempotency classification,
and capacity preflight live in
:mod:`yoke_core.domain.worktree_create_plan`.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Tuple

from yoke_core.domain import project_settings, runtime_settings
from yoke_core.domain.project_checkout_locations import checkout_for_project_slug
from yoke_core.domain.worktree_create_db import (
    check_path_claim_gate,
    item_worktree_authority_is_https,
    persist_item_worktrees,
    prepare_authoritative_item_worktrees,
)
from yoke_core.domain.worktree_create_plan import (
    WorktreeCreationEntry,
    dirty_main_error,
    preflight_worktree_plan,
)
from yoke_core.domain.worktree_lane_plan import (
    resolve_worktree_lanes_for_item,
)
from yoke_core.domain.worktree_paths import (
    _normalize_repo_root,
    _resolve_config_path,
    _resolve_repo_root_from_cwd,
)
from yoke_core.domain.worktree_provision import (
    count_active_worktrees as _count_active_worktrees,
    project_field as _project_field,
    provision_worktree as _provision_worktree,
)


@dataclass
class CreateWorktreeResult:
    # ``path``/``branch``/``created`` mirror the primary worktree for
    # backward compatibility with single-worktree callers. Multi-worktree
    # callers consume ``worktrees`` for per-worktree structured detail.
    path: str
    branch: str
    created: bool
    error: Optional[str] = None
    worktrees: Tuple[WorktreeCreationEntry, ...] = field(default_factory=tuple)
    failed_branch: str = ""


def create_worktree(
    item_id: int,
    base_branch: Optional[str] = None,
    project: Optional[str] = None,
    *,
    repo_root: Optional[str] = None,
    project_db_get: Optional[object] = None,
    config_path: Optional[str] = None,
    scripts_dir: Optional[str] = None,
    db_path: Optional[str] = None,
) -> CreateWorktreeResult:
    """Create git worktrees for a backlog item.

    Resolves the worktree list internally and runs one per-worktree
    provisioning loop. Worktree creation mutates the filesystem and the
    universal lane registry; the session's authority over
    the new worktree comes from its active ``work_claims`` row, validated
    per-call by ``lint_session_cwd``.
    """
    if scripts_dir is None:
        from yoke_core.api.repo_root import find_repo_root

        scripts_dir = str(
            find_repo_root(Path(__file__)) / ".agents" / "skills" / "yoke" / "scripts"
        )

    fallback_branch = f"YOK-{item_id}"
    repo_root_was_explicit = repo_root is not None

    # --- Resolve repo root ---
    if repo_root is None:
        if project:
            # Resolve the project slug to its machine-local checkout through
            # the transport-aware relay so this works over an https control
            # plane, not only a local Postgres connection. The hosted-lane
            # path below already relays; only this slug->id read did not.
            checkout = checkout_for_project_slug(project)
            repo_root = str(checkout) if checkout is not None else ""
            if not repo_root or not os.path.isdir(os.path.join(repo_root, ".git")):
                return CreateWorktreeResult(
                    path="",
                    branch=fallback_branch,
                    created=False,
                    error=(
                        f"project '{project}' has no machine-local git checkout mapping"
                    ),
                )
        else:
            repo_root = _resolve_repo_root_from_cwd()
            if not repo_root:
                return CreateWorktreeResult(
                    path="",
                    branch=fallback_branch,
                    created=False,
                    error="Not in a git repository",
                )
    else:
        repo_root = _normalize_repo_root(repo_root)
        if not repo_root:
            return CreateWorktreeResult(
                path="",
                branch=fallback_branch,
                created=False,
                error=f"repo_root '{repo_root}' is not a git repository",
            )

    if config_path is None:
        config_path = _resolve_config_path(repo_root)

    if base_branch is None:
        if project:
            base_branch = (
                _project_field(project, "default_branch", scripts_dir, project_db_get)
                or "main"
            )
        else:
            base_branch = project_settings.get_project_str(
                repo_root,
                "base_branch",
                config_path=config_path,
            )

    wt_dir = project_settings.get_project_str(
        repo_root,
        "worktrees_dir",
        config_path=config_path,
    )
    worktrees_dir = os.path.join(repo_root, wt_dir)

    hosted_lane_authority = (
        db_path is None and item_worktree_authority_is_https()
    )
    authoritative_lanes = None

    # --- Per-item path-claim activation gate / hosted lane preparation ---
    # The gate is item-level: one claim covers every worktree's path.
    # Skips silently when no claims exist, all claims are terminal, or the
    # path_claims table itself is absent (minimal fixture).
    if hosted_lane_authority:
        try:
            authoritative_lanes = prepare_authoritative_item_worktrees(
                int(item_id),
            )
        except Exception as exc:  # noqa: BLE001 - preserve relay failure detail
            return CreateWorktreeResult(
                path="",
                branch=fallback_branch,
                created=False,
                error=f"authoritative worktree lane preparation failed: {exc}",
            )
    else:
        gate_err = check_path_claim_gate(item_id, db_path)
        if gate_err:
            return CreateWorktreeResult(
                path="",
                branch=fallback_branch,
                created=False,
                error=gate_err,
            )

    if db_path is None:
        db_path = _resolve_db_path_for_worktrees(
            repo_root_was_explicit=repo_root_was_explicit,
        )
    raw_worktrees = resolve_worktree_lanes_for_item(
        int(item_id),
        repo_root,
        wt_dir,
        db_path,
        authoritative_lanes=authoritative_lanes,
    )

    # --- All-worktree preflight (no side effects yet) ---
    max_wt = runtime_settings.get_int(
        "max_active_worktrees",
        5,
        config_path=config_path,
    )
    active_count, active_names = _count_active_worktrees(repo_root, worktrees_dir)
    plan = preflight_worktree_plan(
        raw_worktrees,
        repo_root,
        worktrees_dir,
        max_wt,
        active_count,
        active_names,
    )
    if plan.error:
        primary = plan.primary or (plan.worktrees[0] if plan.worktrees else None)
        return CreateWorktreeResult(
            path=primary.path if (primary and primary.preexisting) else "",
            branch=primary.branch if primary else fallback_branch,
            created=False,
            error=plan.error,
            worktrees=tuple(plan.worktrees),
            failed_branch=plan.failed_branch,
        )
    if plan.pending_worktree_count:
        dirty_error = dirty_main_error(repo_root, worktrees_dir)
        if dirty_error:
            primary = plan.primary or plan.worktrees[0]
            return CreateWorktreeResult(
                path="",
                branch=primary.branch,
                created=False,
                error=dirty_error,
                worktrees=tuple(plan.worktrees),
                failed_branch=primary.branch,
            )

    # --- Per-worktree provisioning loop ---
    os.makedirs(worktrees_dir, exist_ok=True)
    project_for_install = project or _fallback_project_for_worktree()
    for entry in plan.worktrees:
        if entry.preexisting:
            continue
        err = _provision_worktree(
            entry, repo_root, base_branch, project_for_install, scripts_dir
        )
        if err:
            entry.error = err
            return CreateWorktreeResult(
                path="",
                branch=entry.branch,
                created=False,
                error=err,
                worktrees=tuple(plan.worktrees),
                failed_branch=entry.branch,
            )
        entry.created = True

    # --- Stable primary result plus universal lane persistence ---
    primary = plan.primary or plan.worktrees[0]
    any_created = any(entry.created for entry in plan.worktrees)
    try:
        persist_item_worktrees(
            int(item_id),
            [
                (entry.lane_id, entry.branch, entry.path, entry.lane_role)
                for entry in plan.worktrees
            ],
            db_path,
        )
    except Exception as exc:  # noqa: BLE001 - preserve physical lane evidence
        return CreateWorktreeResult(
            path=primary.path,
            branch=primary.branch,
            created=any_created,
            error=(
                "worktree provisioning completed but item-lane persistence "
                f"failed: {exc}"
            ),
            worktrees=tuple(plan.worktrees),
            failed_branch=primary.branch,
        )
    return CreateWorktreeResult(
        path=primary.path,
        branch=primary.branch,
        created=any_created,
        worktrees=tuple(plan.worktrees),
    )


def _resolve_db_path_for_worktrees(*, repo_root_was_explicit: bool) -> Optional[str]:
    return None


def _fallback_project_for_worktree() -> str:
    return "yoke"
