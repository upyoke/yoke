"""Client-side materialization of project-owned deployment-flow declarations."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from yoke_cli.commands._helpers import ensure_handlers_loaded
from yoke_cli.project_install.files import ProjectInstallError
from yoke_cli.transport.dispatcher import build_actor, call_dispatcher
from yoke_contracts.api.function_call import TargetRef
from yoke_contracts.project_contract.deployment_flows import (
    DECLARATION_RELATIVE_PATH,
    validate_declaration_shape,
)


def declaration_path(repo_root: Path) -> Path:
    return repo_root / DECLARATION_RELATIVE_PATH


def load_declaration(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ProjectInstallError(
            f"deployment flow declaration {path} is unreadable: {exc}"
        ) from exc
    except ValueError as exc:
        raise ProjectInstallError(
            f"deployment flow declaration {path} is invalid JSON: {exc}"
        ) from exc
    if not isinstance(payload, dict):
        raise ProjectInstallError(
            f"deployment flow declaration {path} must contain a JSON object"
        )
    try:
        validate_declaration_shape(payload)
    except ValueError as exc:
        raise ProjectInstallError(
            f"deployment flow declaration {path} has invalid shape: {exc}"
        ) from exc
    return payload


def dispatch_declaration(
    *,
    project: str,
    declaration: dict[str, Any],
    session_id: str | None = None,
    preview_only: bool = False,
):
    ensure_handlers_loaded()
    return call_dispatcher(
        function_id="deployment_flows.reconcile_project",
        target=TargetRef(kind="global", project_id=project),
        payload=declaration,
        options={"preview_only": preview_only} if preview_only else None,
        actor=build_actor(session_id=session_id),
    )


def prepare_project_flow_declaration(
    repo_root: Path,
) -> tuple[Path, dict[str, Any]] | None:
    """Read and locally validate existing project configuration."""
    path = declaration_path(repo_root)
    if not path.is_file():
        return None
    return path, load_declaration(path)


def preflight_project_flow_declaration(
    *,
    project: str,
    prepared: tuple[Path, dict[str, Any]] | None,
    session_id: str | None = None,
) -> None:
    """Ask the server to validate DB-dependent constraints before writes."""
    if prepared is None or not _has_effect(prepared[1]):
        return
    path, declaration = prepared
    response = dispatch_declaration(
        project=project,
        declaration=declaration,
        session_id=session_id,
        preview_only=True,
    )
    if not response.success:
        raise _reconcile_error(path, response)


def sync_project_flow_declarations_for_write(
    *,
    repo_root: Path,
    project: str,
    session_id: str | None = None,
    prepared: tuple[Path, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Materialize the checkout declaration and return install-report data."""
    prepared = prepared or prepare_project_flow_declaration(repo_root)
    if prepared is None:
        path = declaration_path(repo_root)
        return {
            "attempted": False,
            "status": "skipped",
            "path": str(path),
            "message": "declaration file absent",
        }
    path, declaration = prepared
    if not _has_effect(declaration):
        return {
            "attempted": False,
            "status": "skipped",
            "path": str(path),
            "message": "declaration has no flows, default, or retirements",
        }
    response = dispatch_declaration(
        project=project,
        declaration=declaration,
        session_id=session_id,
    )
    if not response.success:
        raise _reconcile_error(path, response)
    return {
        "attempted": True,
        "status": "ok",
        "path": str(path),
        **(response.result or {}),
    }


def _has_effect(declaration: dict[str, Any]) -> bool:
    return bool(
        declaration.get("flows")
        or declaration.get("retire_if_present")
        or "default_flow" in declaration
    )


def _reconcile_error(path: Path, response) -> ProjectInstallError:
    message = (
        response.error.message
        if response.error is not None
        else "deployment flow reconciliation failed"
    )
    return ProjectInstallError(
        f"could not materialize {path}: {message}; repair the declaration "
        "and rerun `yoke project refresh`"
    )


__all__ = [
    "declaration_path",
    "dispatch_declaration",
    "load_declaration",
    "prepare_project_flow_declaration",
    "preflight_project_flow_declaration",
    "sync_project_flow_declarations_for_write",
]
