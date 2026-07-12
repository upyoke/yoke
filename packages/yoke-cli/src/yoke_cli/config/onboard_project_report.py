"""Shared report inputs for project onboarding preview and apply."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from yoke_cli.config.onboard_project_modes import PROJECT_MODE_SOURCE_DEV_ADMIN
from yoke_cli.config.project_github_adoption import (
    GITHUB_ADOPTION_APP_BINDING,
    GITHUB_ADOPTION_BACKLOG_ONLY,
)


def github_auth_target(
    inputs: dict[str, Any],
    *,
    mode: str | None = None,
) -> str:
    """Return the GitHub-auth review/apply target for a project mode."""

    if inputs.get("existing_project_id"):
        return "existing-project"
    if inputs.get("keep_existing_remote"):
        return "keep-existing-remote"
    effective_mode = mode if mode is not None else str(inputs.get("mode") or "")
    if effective_mode == PROJECT_MODE_SOURCE_DEV_ADMIN:
        return "source-dev"
    selected = str(inputs.get("github_adoption") or "").strip()
    if selected in ("", "skip"):
        return (
            GITHUB_ADOPTION_APP_BINDING
            if inputs.get("github_repo")
            else GITHUB_ADOPTION_BACKLOG_ONLY
        )
    return selected


def project_kwargs(
    *,
    inputs: dict[str, Any],
    config_path: Path,
    apply: bool,
    service_api_url: str | None,
    local_connection_selected: bool,
) -> dict[str, Any]:
    return {
        "checkout": inputs["checkout"],
        "slug": inputs["slug"],
        "name": inputs["name"],
        "org": inputs.get("org"),
        "github_repo": inputs.get("github_repo"),
        "github_repository_id": inputs.get("github_repository_id"),
        "github_installation_id": inputs.get("github_installation_id"),
        "default_branch": inputs["default_branch"],
        "public_item_prefix": inputs["public_item_prefix"],
        "existing_project_id": inputs.get("existing_project_id"),
        "github_adoption_choice": inputs.get("github_adoption"),
        "github_adoption_preserve": bool(inputs.get("github_adoption_preserve")),
        "config_path": config_path,
        "apply": apply,
        "service_api_url": service_api_url,
        "local_connection_selected": local_connection_selected,
    }


__all__ = ["github_auth_target", "project_kwargs"]
