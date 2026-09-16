"""Shared project onboarding apply helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from yoke_cli.config import github_git_credentials
from yoke_cli.config import github_repo_helper_reconnect
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
    scaffold_action: str,
    reuse_github_auth: bool,
    clone_outcome: Any | None = None,
    register_mapping: bool = False,
    persist_sync_mode: bool = False,
    service_api_url: str | None = None,
    local_connection_selected: bool = False,
) -> dict[str, Any]:
    project = project_from_result(result)
    project_id = int(project["id"])
    binding_result = (
        None
        if reuse_github_auth
        else (
            progress_steps.store_github_binding(
                progress,
                github_auth_target,
                project,
                github_adoption,
                config_path,
                persist_sync_mode=persist_sync_mode,
                service_api_url=service_api_url,
                local_connection_selected=local_connection_selected,
            )
        )
    )
    if binding_result and binding_result.get("binding"):
        binding = dict(github_adoption.get("binding") or {})
        binding["status"] = str(binding_result["binding"])
        if binding_result.get("permission_status"):
            binding["permission_status"] = dict(binding_result["permission_status"])
        github_adoption["binding"] = binding
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
        install = install_runner.install(
            root,
            project_id=project_id,
            config_path=config_path,
            operation=install_operation(scaffold_action),
            # Reviewed apply; the folder may be a just-cloned or
            # just-inited tree with leftover install dirt.
            force=True,
        )
        github = machine_config.github_config(config_path)
        web_url = str(github.get("web_url") or "")
        if (
            web_url
            and github_repo_helper_reconnect.has_matching_https_remote(
                root,
                web_url=web_url,
            )
            is True
        ):
            install["git_credentials"] = github_git_credentials.configure_repo_helper(
                root,
                config_path=config_path,
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
        operation,
        root,
        project,
        install,
        result,
        github_adoption,
        config_path=config_path,
        binding_result=binding_result,
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
    clone_outcome: Any | None = None,
    scaffold_action: str = "project-install-scaffold",
    reuse_github_auth: bool = False,
    service_api_url: str | None = None,
    local_connection_selected: bool = False,
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
            scaffold_action=scaffold_action,
            reuse_github_auth=reuse_github_auth,
            clone_outcome=clone_outcome,
            register_mapping=True,
            persist_sync_mode=True,
            service_api_url=service_api_url,
            local_connection_selected=local_connection_selected,
        )
    finish_github_binding_if_needed(
        progress,
        github_auth_target,
        github_adoption,
        reuse_github_auth,
    )
    return report


def finish_github_binding_if_needed(
    progress: onboard_apply_progress.ProgressCallback | None,
    github_auth_target: str,
    github_adoption: dict[str, Any],
    reuse_github_auth: bool,
) -> None:
    if not reuse_github_auth:
        progress_steps.finish_github_binding(
            progress, github_auth_target, github_adoption
        )


def register_project_mapping_if_needed(
    root: Path,
    project_id: int,
    config_path: str | Path | None,
) -> None:
    if not project_mapping_needs_write(root, project_id, config_path):
        return
    # Operator-driven onboarding Apply: previewed and confirmed before this
    # runs, so a slot already routed elsewhere is a deliberate move.
    machine_writer.register_project(
        root,
        int(project_id),
        reassign=True,
        path=config_path,
    )


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
