"""Filesystem provisioning helpers for item worktree creation."""

from __future__ import annotations

import os
import sys
from typing import Optional

from yoke_core.domain.worktree_create_plan import WorktreeCreationEntry
from yoke_core.domain.worktree_deps import install_worktree_deps
from yoke_core.domain.worktree_paths import _run


def provision_worktree(
    entry: WorktreeCreationEntry,
    repo_root: str,
    base_branch: str,
    project: str,
    scripts_dir: str,
) -> Optional[str]:
    """Provision one planned lane, returning a blocking git error if any."""
    ref_check = _run([
        "git", "-C", repo_root, "show-ref", "--verify", "--quiet",
        f"refs/heads/{entry.branch}",
    ])
    if ref_check.returncode == 0:
        result = _run([
            "git", "-C", repo_root, "worktree", "add",
            entry.path, entry.branch,
        ])
    else:
        result = _run([
            "git", "-C", repo_root, "worktree", "add",
            entry.path, "-b", entry.branch, base_branch,
        ])
    if result.returncode != 0:
        return (
            f"git worktree add failed for worktree '{entry.branch}': "
            f"{result.stderr.strip()}"
        )

    try:
        install_exit = install_worktree_deps(
            entry.path,
            project_id=project,
            scripts_dir=scripts_dir,
        )
    except Exception as exc:  # noqa: BLE001 — non-fatal best-effort install
        print(
            f"Warning: dependency install failed for worktree "
            f"'{entry.branch}' (non-fatal)",
            file=sys.stderr,
        )
        print(str(exc), file=sys.stderr)
    else:
        if install_exit != 0:
            print(
                f"Warning: dependency install failed for worktree "
                f"'{entry.branch}' (non-fatal)",
                file=sys.stderr,
            )

    provision_worktree_validation_surfaces(entry.path, project)
    return None


def provision_worktree_hook_trust(repo_root: str, worktree_path: str) -> None:
    """Best-effort mirroring of the checkout's Codex hook trust into a lane.

    Codex keys hook trust by the literal hooks-file path, so a worktree
    starts out untrusted and therefore hook-dead. Runs for reused lanes as
    well as new ones, so a worktree created before this step existed becomes
    hook-live the next time it is prepared.
    """
    try:
        from yoke_core.domain.worktree_codex_hook_trust import mirror_hook_trust

        result = mirror_hook_trust(repo_root, worktree_path)
    except Exception as exc:  # noqa: BLE001 — best-effort
        print(
            f"Warning: Codex hook-trust mirroring failed (non-fatal): {exc}",
            file=sys.stderr,
        )
        return

    if result.mirrored:
        print(
            f"Codex hook trust mirrored into {worktree_path}: "
            f"{len(result.mirrored)} entries",
            file=sys.stderr,
        )
    elif result.source_trusted and not result.hooks_fire:
        # Silent when the checkout holds no trusted entries at all: there is
        # nothing to mirror, and a Codex-less machine should not be warned
        # about Codex on every lane it prepares.
        print(
            f"Warning: Codex hooks will not fire in {worktree_path} — "
            f"{result.summary()}",
            file=sys.stderr,
        )


def provision_worktree_harness_enablement(
    repo_root: str,
    worktree_path: str,
) -> None:
    """Apply every manifest-declared harness contribution to a lane."""
    try:
        from yoke_core.domain.worktree_harness_enablement import (
            prepare_worktree_harnesses,
        )

        reports = prepare_worktree_harnesses(repo_root, worktree_path)
    except Exception as exc:  # noqa: BLE001 — best-effort lane provisioning
        print(
            f"Warning: harness lane enablement failed (non-fatal): {exc}",
            file=sys.stderr,
        )
        return

    for report in reports:
        for action in report.actions:
            print(
                f"{report.harness_id} lane enablement: {action}",
                file=sys.stderr,
            )
        for warning in report.warnings:
            print(
                f"Warning: {report.harness_id} lane enablement: {warning}",
                file=sys.stderr,
            )


def provision_worktree_validation_surfaces(
    worktree_path: str,
    project: str,
) -> None:
    """Best-effort provisioning of every declared validation surface."""
    try:
        from yoke_core.domain import worktree_validation_surface as _wvs

        result = _wvs.provision_validation_surfaces(worktree_path, project)
    except Exception as exc:  # noqa: BLE001 — best-effort
        print(
            f"Warning: validation-surface provisioning failed "
            f"(non-fatal): {exc}",
            file=sys.stderr,
        )
        return

    for surface in result.surfaces:
        if surface.error:
            print(
                f"Warning: validation surface for model "
                f"'{surface.model_name}' at {surface.path} failed: "
                f"{surface.error}",
                file=sys.stderr,
            )
        elif surface.created:
            print(
                f"Validation surface provisioned: {surface.model_name} "
                f"-> {surface.path}",
                file=sys.stderr,
            )


def count_active_worktrees(
    repo_root: str,
    worktrees_dir: str,
) -> tuple[int, list[str]]:
    """Return active managed worktree count and branch-directory names."""
    result = _run([
        "git", "-C", repo_root, "worktree", "list", "--porcelain",
    ])
    if result.returncode != 0:
        return 0, []
    paths = [
        line[len("worktree ") :]
        for line in result.stdout.splitlines()
        if line.startswith("worktree ")
    ]
    names = [
        os.path.basename(path)
        for path in paths
        if path.startswith(worktrees_dir + "/")
    ]
    return len(names), names


def project_field(
    project: str,
    field: str,
    scripts_dir: str,
    project_db_get: Optional[object] = None,
) -> Optional[str]:
    """Read one project field through the existing local tool surface."""
    if project_db_get is not None:
        return project_db_get(project, field)
    result = _run([
        sys.executable, "-m", "yoke_core.domain.projects",
        "get", project, field,
    ])
    if result.returncode == 0:
        return result.stdout.strip() or None
    return None


__all__ = [
    "count_active_worktrees",
    "project_field",
    "provision_worktree",
    "provision_worktree_harness_enablement",
    "provision_worktree_hook_trust",
    "provision_worktree_validation_surfaces",
]
