"""Project-install function handlers (``project.install/refresh/uninstall``).

These run the client-side install layer on whatever host dispatches them —
the project repo lives on THIS machine, so like the machine-config writers
they are meaningful in-process and nonsensical to relay to a cloud env.
The handler resolves the bundle itself (the active connection's transport
decides https-fetch vs in-process render).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel

from yoke_core.domain import project_install
from yoke_core.domain.machine_config import MachineConfigError
from yoke_contracts.machine_config.schema import MachineConfigContractError
from yoke_core.domain.machine_config_writer import MachineConfigWriteError
from yoke_core.domain.project_install import ProjectInstallError
from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)


class ProjectInstallRequest(BaseModel):
    repo_root: Optional[str] = None
    project_id: Optional[int] = None
    env: Optional[str] = None
    config_path: Optional[str] = None
    # Compatibility-only delivery override. Source-link setup is no longer a
    # project-install mode; Yoke source checkouts route to `yoke dev setup`.
    mode: Optional[str] = None


class ProjectInstallResponse(BaseModel):
    operation: str
    mode: str
    repo_root: str
    yoke_version: str
    source: str
    manifest: str
    machine_config_newly_registered: bool
    warnings: List[str]
    # Copy-strategy fields (absent from source-link reports).
    project_id: Optional[int] = None
    project_slug: Optional[str] = None
    files_written: Optional[List[str]] = None
    files_unchanged: Optional[int] = None
    files_pruned: Optional[List[str]] = None
    files_skipped_modified: Optional[List[str]] = None
    hooks_added: Optional[Dict[str, Any]] = None
    created_settings_files: Optional[List[str]] = None
    # Source-link-strategy fields (absent from copy reports).
    symlinks_created: Optional[int] = None
    symlinks_ok: Optional[int] = None
    actions: Optional[List[str]] = None


class ProjectUninstallRequest(BaseModel):
    repo_root: Optional[str] = None
    config_path: Optional[str] = None


class ProjectUninstallResponse(BaseModel):
    operation: str
    mode: str
    repo_root: str
    files_removed: List[str]
    files_skipped_modified: List[str]
    files_already_absent: List[str]
    hooks_removed: Dict[str, Any]
    git_hooks_removed: List[str]
    settings_files_deleted: List[str]
    manifest_removed: bool
    warnings: List[str]


def _install_args(request: FunctionCallRequest) -> Dict[str, Any]:
    payload = request.payload or {}
    return {
        "repo_root": payload.get("repo_root"),
        "project_id": payload.get("project_id"),
        "explicit_env": payload.get("env"),
        "config_path": payload.get("config_path"),
        "mode": payload.get("mode"),
    }


def handle_project_install(request: FunctionCallRequest) -> HandlerOutcome:
    return _outcome(lambda: project_install.install(**_install_args(request)))


def handle_project_refresh(request: FunctionCallRequest) -> HandlerOutcome:
    return _outcome(lambda: project_install.refresh(**_install_args(request)))


def handle_project_uninstall(request: FunctionCallRequest) -> HandlerOutcome:
    payload = request.payload or {}
    return _outcome(lambda: project_install.uninstall(
        payload.get("repo_root"), config_path=payload.get("config_path"),
    ))


def _outcome(operation) -> HandlerOutcome:
    try:
        result = operation()
    except (ProjectInstallError, MachineConfigError,
            MachineConfigContractError, MachineConfigWriteError) as exc:
        return HandlerOutcome(
            primary_success=False,
            error=FunctionError(
                code="project_install_failed",
                message=str(exc),
            ),
        )
    return HandlerOutcome(result_payload=result, primary_success=True)


__all__ = [
    "ProjectInstallRequest",
    "ProjectInstallResponse",
    "ProjectUninstallRequest",
    "ProjectUninstallResponse",
    "handle_project_install",
    "handle_project_refresh",
    "handle_project_uninstall",
]
