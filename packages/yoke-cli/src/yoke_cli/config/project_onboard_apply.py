"""Shared project onboarding apply helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from yoke_cli.config import dev_setup
from yoke_cli.config import github_git_credentials
from yoke_cli.config import machine_config
from yoke_cli.config import onboard_apply_progress
from yoke_cli.config import project_onboard_progress as progress_steps
from yoke_cli.config import project_git_prerequisite
from yoke_cli.config import writer as machine_writer
from yoke_cli.config.project_onboard_support import (
    applied_report,
    dispatch,
    ProjectOnboardError,
    project_from_result,
)
from yoke_cli.project_install import runner as install_runner
from yoke_cli.project_install import source_dev

# The onboard operation label for the "Develop Yoke itself" (source-dev-admin)
# flow. onboard_project builds it; this module gates the source-link install on it.
SOURCE_DEV_ADMIN_OPERATION = "onboard.source-dev-admin"


def ensure_git_available() -> None:
    try:
        project_git_prerequisite.require_git_available()
    except project_git_prerequisite.MissingGitError as exc:
        raise ProjectOnboardError(str(exc)) from exc


def finish_after_dispatch(
    *,
    operation: str,
    root: Path,
    result: dict[str, Any],
    github_adoption: dict[str, Any],
    config_path: str | Path | None,
    progress: onboard_apply_progress.ProgressCallback | None,
    github_auth_target: str,
    token_value: str | None,
    scaffold_action: str,
    reuse_github_auth: bool,
    clone_outcome: Any | None = None,
    register_mapping: bool = False,
) -> dict[str, Any]:
    project = project_from_result(result)
    project_id = int(project["id"])
    secret_result = None if reuse_github_auth else (
        progress_steps.store_github_binding(
            progress, github_auth_target, project, token_value, github_adoption,
            config_path,
        )
    )
    mapping_needed = project_mapping_needs_write(root, project_id, config_path)
    if register_mapping and mapping_needed:
        with onboard_apply_progress.step(
            progress,
            "project-checkout-register",
            str(root),
        ):
            register_project_mapping_if_needed(root, project_id, config_path)
        mapping_needed = False
    elif mapping_needed:
        onboard_apply_progress.emit(
            progress,
            "project-checkout-register",
            str(root),
            "running",
        )
    try:
        if source_dev.is_yoke_source_checkout(root):
            # "Develop Yoke itself" onboarding: apply the source-link dev layer
            # (symlinks + git hooks) now — it runs in a subprocess with the checkout
            # on PYTHONPATH, so it needs no editable install yet. The editable
            # install that repoints `yoke` at the checkout is DEFERRED to after the
            # wizard UI closes (it deletes the product wheel this process runs from);
            # record the pending checkout so the post-UI step can finish it.
            try:
                install = dev_setup.install_source_checkout(
                    root, editable_install=False,
                )
            except dev_setup.DevSetupError as exc:
                raise ProjectOnboardError(str(exc)) from exc
            git_credentials = github_git_credentials.configure_repo_helper(
                root, config_path=config_path,
            )
            install["git_credentials"] = git_credentials
            # Product installs carry project_id from the bundle; source-link does
            # not, but the onboarding handoff (checkout-binding evidence) needs it.
            install["project_id"] = project_id
            record_pending_dev_install(root, config_path)
        elif operation == SOURCE_DEV_ADMIN_OPERATION:
            # Source-dev onboarding must land on a real Yoke checkout (the clone
            # step provides it). If it did not, refuse — never product-install a
            # scaffold into a non-Yoke folder and report success.
            raise ProjectOnboardError(
                f"{root} is not a Yoke source checkout after setup. Re-run "
                "'Develop Yoke itself' with an empty folder to clone into, or "
                "point at an existing Yoke clone."
            )
        else:
            install = install_runner.install(
                root, project_id=project_id, config_path=config_path,
                operation=install_operation(scaffold_action),
            )
    except Exception:
        if mapping_needed:
            onboard_apply_progress.emit(
                progress,
                "project-checkout-register",
                str(root),
                "failed",
            )
        raise
    if mapping_needed:
        try:
            if not install.get("machine_config_newly_registered"):
                register_project_mapping_if_needed(root, project_id, config_path)
        except Exception:
            onboard_apply_progress.emit(
                progress,
                "project-checkout-register",
                str(root),
                "failed",
            )
            raise
        onboard_apply_progress.emit(
            progress,
            "project-checkout-register",
            str(root),
            "done",
        )
    return applied_report(
        operation, root, project, install, result, github_adoption,
        config_path=config_path,
        secret_result=secret_result,
        clone_outcome=clone_outcome,
    )


def install_existing_project(
    *,
    operation: str,
    root: Path,
    project_key: str,
    github_adoption: dict[str, Any],
    config_path: str | Path | None,
    progress: onboard_apply_progress.ProgressCallback | None,
    github_auth_target: str,
    token_value: str | None,
    clone_outcome: Any | None = None,
    scaffold_action: str = "project-install-scaffold",
    reuse_github_auth: bool = False,
) -> dict[str, Any]:
    with onboard_apply_progress.step(progress, scaffold_action):
        result = dispatch("projects.get", {"project": project_key}, config_path)
        report = finish_after_dispatch(
            operation=operation,
            root=root,
            result=result,
            github_adoption=github_adoption,
            config_path=config_path,
            progress=progress,
            github_auth_target=github_auth_target,
            token_value=token_value,
            scaffold_action=scaffold_action,
            reuse_github_auth=reuse_github_auth,
            clone_outcome=clone_outcome,
            register_mapping=True,
        )
    finish_github_binding_if_needed(
        progress, github_auth_target, github_adoption, reuse_github_auth,
    )
    return report


def finish_github_binding_if_needed(
    progress: onboard_apply_progress.ProgressCallback | None,
    github_auth_target: str,
    github_adoption: dict[str, Any],
    reuse_github_auth: bool,
) -> None:
    if not reuse_github_auth:
        progress_steps.finish_github_binding(progress, github_auth_target, github_adoption)


def register_project_mapping_if_needed(
    root: Path,
    project_id: int,
    config_path: str | Path | None,
) -> None:
    if not project_mapping_needs_write(root, project_id, config_path):
        return
    machine_writer.register_project(root, int(project_id), path=config_path)


def project_mapping_needs_write(
    root: Path,
    project_id: int,
    config_path: str | Path | None,
) -> bool:
    return machine_config.project_id(root, config_path) != int(project_id)


def install_operation(scaffold_action: str) -> str:
    return "refresh" if scaffold_action == "project-refresh-scaffold" else "install"


def existing_project_key(existing_project_id: int | None, slug: str) -> str:
    return str(existing_project_id) if existing_project_id is not None else slug


def _pending_dev_install_marker(config_path: str | Path | None) -> Path:
    return machine_config.config_path(config_path).parent / ".pending-dev-install"


def record_pending_dev_install(root: Path, config_path: str | Path | None) -> None:
    """Record a Yoke checkout awaiting its deferred editable install (run post-UI)."""
    marker = _pending_dev_install_marker(config_path)
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(str(root), encoding="utf-8")


def pop_pending_dev_install(config_path: str | Path | None) -> str | None:
    """Return + clear the checkout awaiting its deferred editable install, if any."""
    marker = _pending_dev_install_marker(config_path)
    if not marker.is_file():
        return None
    root = marker.read_text(encoding="utf-8").strip()
    try:
        marker.unlink()
    except OSError:
        pass
    return root or None


__all__ = [
    "ensure_git_available",
    "existing_project_key",
    "finish_github_binding_if_needed",
    "finish_after_dispatch",
    "install_existing_project",
    "pop_pending_dev_install",
    "project_mapping_needs_write",
    "record_pending_dev_install",
    "register_project_mapping_if_needed",
]
