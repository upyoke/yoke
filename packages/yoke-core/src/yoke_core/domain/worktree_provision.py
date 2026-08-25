"""Filesystem provisioning helpers for item worktree creation."""

from __future__ import annotations

import os
import sys
from typing import Optional

from yoke_core.domain.worktree_create_plan import WorktreeCreationEntry
from yoke_core.domain.worktree_deps import install_worktree_deps
from yoke_core.domain.worktree_paths import _run, captured_process_detail
from yoke_contracts.project_contract.file_line_policy import item_base_config_key

GIT_WORKTREE_ADD_TIMEOUT_SECONDS = 600


def provision_worktree(
    entry: WorktreeCreationEntry,
    repo_root: str,
    base_branch: str,
    project: str,
    scripts_dir: str,
) -> Optional[str]:
    """Provision one planned lane, returning a blocking git error if any."""
    ref_check = _run(
        [
            "git",
            "-C",
            repo_root,
            "show-ref",
            "--verify",
            "--quiet",
            f"refs/heads/{entry.branch}",
        ]
    )
    config_key = item_base_config_key(entry.branch)
    recorded = _run(["git", "-C", repo_root, "config", "--get", config_key])
    if recorded.returncode != 0:
        base_args = (
            ["merge-base", entry.branch, base_branch]
            if ref_check.returncode == 0
            else ["rev-parse", base_branch]
        )
        base = _run(["git", "-C", repo_root, *base_args])
        if base.returncode != 0:
            return (
                f"could not resolve item base {base_branch!r}: "
                f"{captured_process_detail(base)}"
            )
        recorded = _run(
            [
                "git",
                "-C",
                repo_root,
                "config",
                config_key,
                base.stdout.strip(),
            ]
        )
        if recorded.returncode != 0:
            return (
                f"could not record item base for '{entry.branch}': "
                f"{captured_process_detail(recorded)}"
            )
    add_cmd = (
        ["git", "-C", repo_root, "worktree", "add", entry.path, entry.branch]
        if ref_check.returncode == 0
        else [
            "git",
            "-C",
            repo_root,
            "worktree",
            "add",
            entry.path,
            "-b",
            entry.branch,
            base_branch,
        ]
    )
    result = _run(add_cmd, timeout=GIT_WORKTREE_ADD_TIMEOUT_SECONDS)
    if result.returncode != 0:
        return (
            f"git worktree add failed for worktree '{entry.branch}': "
            f"{captured_process_detail(result)}"
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


def provision_worktree_test_environment(
    worktree_path: str,
    *,
    project: Optional[str] = None,
) -> Optional[str]:
    """Install and prove a lane's test environment; return a blocking error.

    Unlike the best-effort provisioning around it, this one blocks. A lane
    that cannot run its own tests is not ready, and the alternative — a
    warning nobody acts on, followed by an unattributable import error at
    the first test command — is the failure this step exists to end.

    Bytecode hygiene runs first and on reused lanes as well as new ones:
    stale ``__pycache__`` is what makes a long-lived lane disagree with a
    clean checkout of the same commit.
    """
    from yoke_core.domain.worktree_lane_hygiene import purge_lane_bytecode_caches
    from yoke_core.domain.worktree_test_environment import (
        provision_test_environment,
    )

    try:
        hygiene = purge_lane_bytecode_caches(worktree_path)
    except Exception as exc:  # noqa: BLE001 — a dirty cache must name its cause
        return f"Lane bytecode hygiene failed for {worktree_path}: {exc}"
    for action in hygiene.actions:
        print(f"Lane hygiene: {action}", file=sys.stderr)
    if hygiene.error:
        return f"Lane bytecode hygiene failed for {worktree_path}: {hygiene.error}"

    try:
        report = provision_test_environment(worktree_path, project=project)
    except Exception as exc:  # noqa: BLE001 — a broken lane must name its cause
        return f"Lane test environment provisioning failed for {worktree_path}: {exc}"
    for action in report.actions:
        print(f"Lane test environment: {action}", file=sys.stderr)
    return report.error or None


def provision_worktree_validation_surfaces(
    worktree_path: str,
    project: str,
) -> None:
    """Best-effort provisioning of every declared validation surface."""
    try:
        from yoke_core.domain import worktree_validation_surface as _wvs

        result = _wvs.provision_validation_surfaces(worktree_path, project)
    except Exception as exc:  # noqa: BLE001 — best-effort
        from yoke_core.domain.yoke_connected_env import (
            ConnectedEnvNotLocalPostgres,
        )

        if isinstance(exc.__cause__, ConnectedEnvNotLocalPostgres):
            return
        print(
            f"Warning: validation-surface provisioning failed (non-fatal): {exc}",
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
    result = _run(
        [
            "git",
            "-C",
            repo_root,
            "worktree",
            "list",
            "--porcelain",
        ]
    )
    if result.returncode != 0:
        return 0, []
    paths = [
        line[len("worktree ") :]
        for line in result.stdout.splitlines()
        if line.startswith("worktree ")
    ]
    names = [
        os.path.basename(path) for path in paths if path.startswith(worktrees_dir + "/")
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
    result = _run(
        [
            sys.executable,
            "-m",
            "yoke_core.domain.projects",
            "get",
            project,
            field,
        ]
    )
    if result.returncode == 0:
        return result.stdout.strip() or None
    return None


__all__ = [
    "count_active_worktrees",
    "project_field",
    "provision_worktree",
    "provision_worktree_harness_enablement",
    "provision_worktree_hook_trust",
    "provision_worktree_test_environment",
    "provision_worktree_validation_surfaces",
]
