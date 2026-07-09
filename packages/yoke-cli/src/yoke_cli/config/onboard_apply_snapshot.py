"""Replay-safe input metadata for ``yoke onboard`` apply reports."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from yoke_cli.config import onboard_project

_PROJECT_MODES_THAT_CREATE_CHECKOUTS = {
    onboard_project.PROJECT_MODE_CREATE_REPO,
    onboard_project.PROJECT_MODE_CLONE_REMOTE,
    onboard_project.PROJECT_MODE_IMPORT_REMOTE,
}


def build(kwargs: Mapping[str, Any]) -> dict[str, Any]:
    """Return a JSON-safe snapshot of non-secret apply inputs."""
    project_mode = _text(kwargs.get("project_mode") or onboard_project.PROJECT_MODE_MACHINE_ONLY)
    checkout = _text(kwargs.get("project_checkout"))
    return {
        "config_path": _text(kwargs.get("config_path")),
        "env_name": _text(kwargs.get("env_name")),
        "api_url": _text(kwargs.get("api_url")),
        "destination": _text(kwargs.get("destination")),
        "mode": _text(kwargs.get("mode")),
        "check_identity": bool(kwargs.get("check_identity")),
        "credential_sources": _credential_sources(kwargs),
        "machine_github": _machine_github(kwargs),
        "project": _project(kwargs, project_mode),
        "checkout_provenance": _checkout_provenance(project_mode, checkout),
    }


def _machine_github(kwargs: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "choice": _text(kwargs.get("machine_github_choice")),
        "api_url": _text(kwargs.get("machine_github_api_url")),
        "authorization_source": _github_authorization_source(kwargs),
    }


def _project(kwargs: Mapping[str, Any], project_mode: str) -> dict[str, Any]:
    return {
        "mode": project_mode,
        "remote_url": _text(kwargs.get("project_remote_url")),
        "checkout": _text(kwargs.get("project_checkout")),
        "slug": _text(kwargs.get("project_slug")),
        "name": _text(kwargs.get("project_name")),
        "org": _text(kwargs.get("project_org")),
        "github_repo": _text(kwargs.get("project_github_repo")),
        "default_branch": _text(kwargs.get("project_default_branch")),
        "default_branch_source": _text(kwargs.get("project_default_branch_source")),
        "public_item_prefix": _text(kwargs.get("project_public_item_prefix")),
        "existing_project_id": kwargs.get("existing_project_id"),
        "existing_project_match_source": _text(
            kwargs.get("existing_project_match_source")
        ),
        "existing_project_local_source": _text(
            kwargs.get("existing_project_local_source")
        ),
        "github_adoption": _text(kwargs.get("project_github_adoption")),
        "github_binding": _github_binding(kwargs),
        "keep_existing_remote": bool(kwargs.get("project_keep_existing_remote")),
        "publish": _publish(kwargs.get("project_publish")),
        "clone": _clone(kwargs.get("project_clone")),
    }


def _credential_sources(kwargs: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "yoke": {
            "kind": _text(kwargs.get("token_source_kind") or "argument"),
            "path": _text(kwargs.get("token_file")),
        },
        "github_app": {
            "machine": _github_authorization_source(kwargs),
            "project": _github_binding(kwargs),
        },
    }


def _github_authorization_source(kwargs: Mapping[str, Any]) -> dict[str, Any]:
    choice = _text(kwargs.get("machine_github_choice"))
    if choice == "connect":
        return {"kind": "github_app_user_authorization"}
    return {"kind": ""}


def _github_binding(kwargs: Mapping[str, Any]) -> dict[str, Any]:
    adoption = _text(kwargs.get("project_github_adoption"))
    repo = _text(kwargs.get("project_github_repo"))
    status = _text(kwargs.get("project_github_binding_status"))
    if not status:
        if adoption in {"skip", "backlog-only"} or not repo:
            status = "backlog_only"
        else:
            status = "pending_app_connection"
    return {
        "adoption": adoption,
        "repo": repo,
        "installation_id": _text(kwargs.get("project_github_installation_id")),
        "repository_id": _text(kwargs.get("project_github_repository_id")),
        "status": status,
        "permission_status": _mapping(kwargs.get("project_github_permission_status")),
        "automation": _mapping(kwargs.get("project_github_automation")),
    }


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _checkout_provenance(project_mode: str, checkout: str) -> dict[str, Any]:
    existed = _path_existed(checkout) if checkout else None
    created_by_run = (
        bool(checkout)
        and project_mode in _PROJECT_MODES_THAT_CREATE_CHECKOUTS
        and existed is False
    )
    return {
        "path": checkout,
        "project_mode": project_mode,
        "existed_before_apply": existed,
        "created_by_run": created_by_run,
        "safe_to_remove_on_start_over": created_by_run,
    }


def _publish(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    return {
        "owner": _text(getattr(value, "owner", "")),
        "name": _text(getattr(value, "name", "")),
        "user_login": _text(getattr(value, "user_login", "")),
        "api_url": _text(getattr(value, "api_url", "")),
        "private": bool(getattr(value, "private", True)),
    }


def _clone(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    return {
        "outcome": _text(getattr(value, "outcome", "")),
        "keep_upstream": bool(getattr(value, "keep_upstream", True)),
        "fork_api_url": _text(getattr(value, "fork_api_url", "")),
        "publish": _publish(getattr(value, "publish", None)),
    }


def _path_existed(value: str) -> bool | None:
    try:
        return Path(value).expanduser().exists()
    except OSError:
        return None


def _text(value: Any) -> str:
    return str(value or "")


__all__ = ["build"]
