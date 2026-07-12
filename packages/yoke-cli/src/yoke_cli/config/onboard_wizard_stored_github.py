"""Read-only hydration of saved GitHub state for the onboarding wizard."""

from __future__ import annotations

from pathlib import Path

from yoke_contracts import github_origin
from yoke_cli.config import machine_config


def stored_api_url(config_path: str | Path | None) -> str | None:
    """Return the saved GitHub API URL, or None when no connection is usable."""

    try:
        github = machine_config.github_config(config_path)
    except (OSError, RuntimeError, ValueError):
        return None
    if not github:
        return None
    return str(
        github.get("api_url") or github_origin.DEFAULT_GITHUB_API_URL
    ).strip()


__all__ = ["stored_api_url"]
