"""GitHub App connection helpers for onboarding wizard state."""

from __future__ import annotations

from typing import Any

from yoke_contracts import github_origin
from yoke_cli.config import github_user_tokens
from yoke_cli.config import machine_config


def connected(result: Any) -> bool:
    """Whether the wizard has verified a machine GitHub App connection."""
    verification = getattr(result, "machine_github_verification", None)
    return bool(isinstance(verification, dict) and verification.get("ok"))


def user_access_token(result: Any) -> str | None:
    """Resolve short-lived user access without retaining it in wizard state."""
    config_path = getattr(result, "config_path", None)
    if not machine_config.github_config(config_path):
        return None
    return github_user_tokens.access_token_from_machine_config(
        config_path=config_path,
    ).access_token


def web_url(result: Any) -> str:
    """Return the connected deployment's validated browser base URL."""
    return endpoint_pair(result).web.base_url


def administration_allowed(result: Any) -> bool:
    """Whether the selected owner has a live optional Administration grant."""
    config = machine_config.github_config(getattr(result, "config_path", None))
    owner = str(getattr(result, "project_publish_owner", None) or "").casefold()
    return any(
        isinstance(row, dict) and isinstance(row.get("permissions"), dict)
        and str(row.get("account_login") or "").casefold() == owner
        and not row.get("suspended")
        and row["permissions"].get("administration") == "write"
        for row in config.get("installations") or []
    )


def endpoint_pair(result: Any) -> github_origin.GitHubEndpointPair:
    """Return the connected deployment's validated API/browser endpoints."""
    config = machine_config.github_config(getattr(result, "config_path", None))
    return github_origin.validate_github_endpoint_pair(
        str(config.get("api_url") or github_origin.DEFAULT_GITHUB_API_URL),
        str(config.get("web_url") or github_origin.DEFAULT_GITHUB_WEB_URL),
    )


__all__ = [
    "administration_allowed",
    "connected",
    "endpoint_pair",
    "user_access_token",
    "web_url",
]
