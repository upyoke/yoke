"""Worktree creation surface.

Owns ``create_worktree`` and its per-worktree provisioning loop. A
single-worktree issue is the N=1 case of an N-worktree epic — the creator
resolves the worktree list internally (single-worktree fallback for
issues, ``epic_dispatch_chains`` rows for epics) and runs one provisioning
path covering both shapes. Worktree planning, idempotency classification,
and capacity preflight live in
:mod:`yoke_core.domain.worktree_create_plan`.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Tuple

from yoke_core.domain import project_settings, runtime_settings
from yoke_core.domain.db_helpers import connect
from yoke_core.domain.project_checkout_locations import checkout_for_project
from yoke_core.domain.worktree_create_db import (
    check_path_claim_gate,
    persist_item_worktree,
)
from yoke_core.domain.worktree_create_plan import (
    WorktreeCreationEntry,
    dirty_main_error,
    preflight_worktree_plan,
    resolve_worktrees_for_item,
)
from yoke_core.domain.worktree_deps import install_worktree_deps
from yoke_core.domain.worktree_paths import (
    _normalize_repo_root,
    _resolve_config_path,
    _resolve_repo_root_from_cwd,
    _run,
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

    Resolves the worktree list internally (single-worktree fallback for
    issues, ``epic_dispatch_chains`` rows for epics) and runs one
    per-worktree provisioning loop. Worktree creation is a pure
    filesystem + ``items.worktree`` mutation; the session's authority over
    the new worktree comes from its active ``work_claims`` row, validated
    per-call by ``lint_session_cwd``.
    """
    if scripts_dir is None:
        from yoke_core.api.repo_root import find_repo_root

        scripts_dir = str(
            find_repo_root(Path(__file__))
            / ".agents" / "skills" / "yoke" / "scripts"
        )

    fallback_branch = f"YOK-{item_id}"
    repo_root_was_explicit = repo_root is not None

    # --- Resolve repo root ---
    if repo_root is None:
        if project:
            with connect(db_path) as conn:
                checkout = checkout_for_project(conn, project)
            repo_root = str(checkout) if checkout is not None else ""
            if not repo_root or not os.path.isdir(os.path.join(repo_root, ".git")):
                return CreateWorktreeResult(
                    path="", branch=fallback_branch, created=False,
                    error=(
                        f"project '{project}' has no machine-local git "
                        "checkout mapping"
                    ),
                )
        else:
            repo_root = _resolve_repo_root_from_cwd()
            if not repo_root:
                return CreateWorktreeResult(
                    path="", branch=fallback_branch, created=False,
                    error="Not in a git repository",
                )
    else:
        repo_root = _normalize_repo_root(repo_root)
        if not repo_root:
            return CreateWorktreeResult(
                path="", branch=fallback_branch, created=False,
                error=f"repo_root '{repo_root}' is not a git repository",
            )

    if config_path is None:
        config_path = _resolve_config_path(repo_root)

    if base_branch is None:
        if project:
            base_branch = _project_field(project, "default_branch", scripts_dir, project_db_get) or "main"
        else:
            base_branch = project_settings.get_project_str(
                repo_root, "base_branch", config_path=config_path,
            )

    wt_dir = project_settings.get_project_str(
        repo_root, "worktrees_dir", config_path=config_path,
    )
    worktrees_dir = os.path.join(repo_root, wt_dir)

    # --- Per-item path-claim activation gate ---
    # The gate is item-level: one claim covers every worktree's path.
    # Skips silently when no claims exist, all claims are terminal, or the
    # path_claims table itself is absent (minimal fixture).
    gate_err = check_path_claim_gate(item_id, db_path)
    if gate_err:
        return CreateWorktreeResult(
            path="", branch=fallback_branch, created=False, error=gate_err,
        )

    if db_path is None:
        db_path = _resolve_db_path_for_worktrees(
            repo_root_was_explicit=repo_root_was_explicit,
        )
    raw_worktrees = resolve_worktrees_for_item(int(item_id), repo_root, wt_dir, db_path)

    # --- All-worktree preflight (no side effects yet) ---
    max_wt = runtime_settings.get_int(
        "max_active_worktrees", 5, config_path=config_path,
    )
    active_count, active_names = _count_active_worktrees(repo_root, worktrees_dir)
    plan = preflight_worktree_plan(
        raw_worktrees, repo_root, worktrees_dir, max_wt, active_count, active_names,
    )
    if plan.error:
        primary = plan.primary or (plan.worktrees[0] if plan.worktrees else None)
        return CreateWorktreeResult(
            path=primary.path if (primary and primary.preexisting) else "",
            branch=primary.branch if primary else fallback_branch,
            created=False, error=plan.error,
            worktrees=tuple(plan.worktrees), failed_branch=plan.failed_branch,
        )
    if plan.pending_worktree_count:
        dirty_error = dirty_main_error(repo_root, worktrees_dir)
        if dirty_error:
            primary = plan.primary or plan.worktrees[0]
            return CreateWorktreeResult(
                path="", branch=primary.branch, created=False,
                error=dirty_error, worktrees=tuple(plan.worktrees),
                failed_branch=primary.branch,
            )

    # --- Per-worktree provisioning loop ---
    os.makedirs(worktrees_dir, exist_ok=True)
    project_for_install = project or _fallback_project_for_worktree()
    for entry in plan.worktrees:
        if entry.preexisting:
            continue
        err = _provision_worktree(entry, repo_root, base_branch, project_for_install, scripts_dir)
        if err:
            entry.error = err
            return CreateWorktreeResult(
                path="", branch=entry.branch, created=False, error=err,
                worktrees=tuple(plan.worktrees), failed_branch=entry.branch,
            )
        entry.created = True

    # --- Backward-compat fields from primary worktree ---
    primary = plan.primary or plan.worktrees[0]
    any_created = any(entry.created for entry in plan.worktrees)
    if any_created:
        persist_item_worktree(int(item_id), primary.branch, db_path)
    return CreateWorktreeResult(
        path=primary.path,
        branch=primary.branch,
        created=any_created,
        worktrees=tuple(plan.worktrees),
    )


def _resolve_db_path_for_worktrees(*, repo_root_was_explicit: bool) -> Optional[str]:
    return None


def _provision_worktree(
    entry: WorktreeCreationEntry,
    repo_root: str,
    base_branch: str,
    project: str,
    scripts_dir: str,
) -> Optional[str]:
    # Returns an error string on failure (caller halts the loop) or None on success.
    ref_check = _run([
        "git", "-C", repo_root, "show-ref", "--verify", "--quiet",
        f"refs/heads/{entry.branch}",
    ])
    if ref_check.returncode == 0:
        r = _run(["git", "-C", repo_root, "worktree", "add", entry.path, entry.branch])
    else:
        r = _run([
            "git", "-C", repo_root, "worktree", "add",
            entry.path, "-b", entry.branch, base_branch,
        ])
    if r.returncode != 0:
        return f"git worktree add failed for worktree '{entry.branch}': {r.stderr.strip()}"

    try:
        install_exit = install_worktree_deps(
            entry.path, project_id=project, scripts_dir=scripts_dir,
        )
    except Exception as exc:  # noqa: BLE001 — non-fatal best-effort install
        print(
            f"Warning: dependency install failed for worktree '{entry.branch}' (non-fatal)",
            file=sys.stderr,
        )
        print(str(exc), file=sys.stderr)
    else:
        if install_exit != 0:
            print(
                f"Warning: dependency install failed for worktree '{entry.branch}' (non-fatal)",
                file=sys.stderr,
            )

    _provision_worktree_validation_surfaces(entry.path, project)
    return None


def _fallback_project_for_worktree() -> str:
    return "yoke"


def _provision_worktree_validation_surfaces(
    worktree_path: str, project: str,
) -> None:
    try:
        from yoke_core.domain import worktree_validation_surface as _wvs

        result = _wvs.provision_validation_surfaces(worktree_path, project)
    except Exception as exc:  # noqa: BLE001 — best-effort
        print(
            f"Warning: validation-surface provisioning failed (non-fatal): {exc}",
            file=sys.stderr,
        )
        return

    for surface in result.surfaces:
        if surface.error:
            print(
                f"Warning: validation surface for model '{surface.model_name}' "
                f"at {surface.path} failed: {surface.error}",
                file=sys.stderr,
            )
        elif surface.created:
            print(
                f"Validation surface provisioned: {surface.model_name} "
                f"-> {surface.path}",
                file=sys.stderr,
            )


def _count_active_worktrees(repo_root: str, worktrees_dir: str) -> tuple:
    r = _run(["git", "-C", repo_root, "worktree", "list", "--porcelain"])
    if r.returncode != 0:
        return 0, []

    count = 0
    names = []
    for line in r.stdout.splitlines():
        if line.startswith("worktree "):
            wt_path = line[len("worktree "):]
            if wt_path.startswith(worktrees_dir + "/"):
                count += 1
                names.append(os.path.basename(wt_path))
    return count, names


def _project_field(
    project: str,
    field: str,
    scripts_dir: str,
    project_db_get: Optional[object] = None,
) -> Optional[str]:
    if project_db_get is not None:
        return project_db_get(project, field)
    r = _run([sys.executable, "-m", "yoke_core.domain.projects", "get", project, field])
    if r.returncode == 0:
        return r.stdout.strip() or None
    return None
