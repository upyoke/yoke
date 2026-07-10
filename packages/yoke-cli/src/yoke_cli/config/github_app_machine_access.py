"""Permission facts derived from the machine's live App installation snapshot."""

from __future__ import annotations

from pathlib import Path
from typing import Mapping

from yoke_cli.config import machine_config
from yoke_contracts import github_app_installation_permissions as permissions


def repository_permission(
    repository: str,
    permission: str,
    required: str,
    *,
    config_path: str | Path | None,
) -> bool | None:
    """Return an installation permission for a visible repository."""
    github = machine_config.github_config(config_path)
    repositories = [
        item for item in github.get("repositories") or []
        if isinstance(item, Mapping)
    ]
    selected = next(
        (item for item in repositories if item.get("full_name") == repository),
        None,
    )
    if selected is None:
        return None
    installation_id = selected.get("installation_id")
    installations = [
        item for item in github.get("installations") or []
        if isinstance(item, Mapping)
    ]
    installation = next(
        (
            item for item in installations
            if item.get("installation_id") == installation_id
        ),
        None,
    )
    if installation is None or installation.get("suspended"):
        return False
    granted = installation.get("permissions")
    if not isinstance(granted, Mapping):
        return False
    level = str(granted.get(permission) or "")
    return permissions.permission_level_satisfies(level, required)


__all__ = ["repository_permission"]
