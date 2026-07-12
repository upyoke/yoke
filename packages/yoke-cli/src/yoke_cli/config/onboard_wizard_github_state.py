"""GitHub App connection helpers for onboarding wizard state."""

from __future__ import annotations

from typing import Any

from yoke_contracts import github_installation_urls, github_origin
from yoke_cli.config import github_local_user_access
from yoke_cli.config import machine_config
from yoke_cli.config import onboard_destinations
from yoke_cli.config import onboard_machine_github


def connected(result: Any) -> bool:
    """Whether the wizard has verified a machine GitHub App connection."""
    verification = getattr(result, "machine_github_verification", None)
    return bool(
        getattr(result, "machine_github_choice", None)
        == onboard_machine_github.CHOICE_CONNECT
        and
        isinstance(verification, dict)
        and verification.get("ok")
        and verification.get("ready")
    )


def user_access_token(result: Any) -> str | None:
    """Resolve short-lived user access without retaining it in wizard state."""
    if not connected(result):
        return None
    config_path = getattr(result, "config_path", None)
    if not machine_config.github_config(config_path):
        return None
    return github_local_user_access.access_token(
        config_path=config_path,
        **connection_scope(result),
    ).access_token


def connection_scope(result: Any) -> dict[str, Any]:
    """Pin GitHub checks to this run's local or HTTPS Yoke destination."""

    selected_service = str(getattr(result, "api_url", "") or "").strip()
    local_selected = (
        getattr(result, "destination", None)
        == onboard_destinations.DESTINATION_LOCAL
    )
    if bool(selected_service) == local_selected:
        raise github_local_user_access.GitHubLocalUserAccessError(
            "the onboarding run does not identify exactly one local or service "
            "Yoke connection"
        )
    return {
        "service_api_url": selected_service or None,
        "local_connection_selected": local_selected,
    }


def web_url(result: Any) -> str:
    """Return the connected deployment's validated browser base URL."""
    return endpoint_pair(result).web.base_url


def clone_web_url(result: Any) -> str:
    """Use saved deployment metadata only for this run's verified connection."""

    if not connected(result):
        return github_origin.DEFAULT_GITHUB_WEB_URL
    return web_url(result)


def repository_access_url(result: Any, *, owner: str | None = None) -> str:
    """Return a validated App settings URL for repository-access management."""

    config = machine_config.github_config(getattr(result, "config_path", None))
    endpoint = github_origin.validate_github_endpoint_pair(
        str(config.get("api_url") or github_origin.DEFAULT_GITHUB_API_URL),
        str(config.get("web_url") or github_origin.DEFAULT_GITHUB_WEB_URL),
    )
    selected_owner = str(owner or "").casefold()
    for installation in config.get("installations") or []:
        if not isinstance(installation, dict):
            continue
        if selected_owner and (
            str(installation.get("account_login") or "").casefold()
            != selected_owner
        ):
            continue
        try:
            return github_installation_urls.validated_settings_url(
                str(installation.get("html_url") or ""),
                web_url=endpoint.web.base_url,
                installation_id=installation.get("installation_id"),
                account_login=str(installation.get("account_login") or ""),
            )
        except github_origin.GitHubApiOriginError:
            continue
    slug = str(config.get("app_slug") or "").strip()
    return endpoint.app_install_url(slug) if slug else endpoint.web.base_url


def administration_allowed(result: Any) -> bool:
    """Whether the selected owner has a live optional Administration grant."""
    config = machine_config.github_config(getattr(result, "config_path", None))
    try:
        if github_origin.validate_github_endpoint_pair(
            str(config.get("api_url") or github_origin.DEFAULT_GITHUB_API_URL),
            str(config.get("web_url") or github_origin.DEFAULT_GITHUB_WEB_URL),
        ).deployment_kind != "github_cloud":
            return False
    except github_origin.GitHubApiOriginError:
        return False
    owner = str(getattr(result, "project_publish_owner", None) or "").casefold()
    return any(
        isinstance(row, dict) and isinstance(row.get("permissions"), dict)
        and str(row.get("account_login") or "").casefold() == owner
        and not row.get("suspended")
        and row.get("repository_selection") == "all"
        and row["permissions"].get("administration") == "write"
        for row in config.get("installations") or []
    )


def fork_ready(result: Any, remote_url: str | None) -> bool:
    """Whether App installation topology satisfies GitHub's fork API rules."""

    if not connected(result) or not remote_url:
        return False
    config = machine_config.github_config(getattr(result, "config_path", None))
    return fork_ready_from_config(config, remote_url)


def fork_ready_from_config(
    config: dict[str, Any], remote_url: str | None,
) -> bool:
    """Whether cached topology satisfies GitHub's fork endpoint permissions."""

    if not remote_url:
        return False
    try:
        if github_origin.validate_github_endpoint_pair(
            str(config.get("api_url") or github_origin.DEFAULT_GITHUB_API_URL),
            str(config.get("web_url") or github_origin.DEFAULT_GITHUB_WEB_URL),
        ).deployment_kind != "github_cloud":
            return False
    except github_origin.GitHubApiOriginError:
        return False
    authorization = config.get("authorization")
    login = str(
        authorization.get("login")
        if isinstance(authorization, dict) else ""
    ).casefold()
    try:
        source = github_origin.normalize_github_repository(
            remote_url,
            web_url=str(
                config.get("web_url") or github_origin.DEFAULT_GITHUB_WEB_URL
            ),
        )
    except github_origin.GitHubApiOriginError:
        return False
    installations = [
        row for row in config.get("installations") or []
        if isinstance(row, dict) and not row.get("suspended")
    ]
    personal_all = any(
        str(row.get("account_type") or "").casefold() == "user"
        and str(row.get("account_login") or "").casefold() == login
        and row.get("repository_selection") == "all"
        and isinstance(row.get("permissions"), dict)
        and row["permissions"].get("contents") == "write"
        and row["permissions"].get("administration") == "write"
        for row in installations
    )
    source_access = any(
        str(repo.get("full_name") or "").casefold() == source.casefold()
        and any(
            row.get("installation_id") == repo.get("installation_id")
            and isinstance(row.get("permissions"), dict)
            and row["permissions"].get("contents") in {"read", "write"}
            and row["permissions"].get("administration") == "write"
            for row in installations
        )
        for repo in config.get("repositories") or []
        if isinstance(repo, dict)
    )
    return personal_all and source_access


def endpoint_pair(result: Any) -> github_origin.GitHubEndpointPair:
    """Return the connected deployment's validated API/browser endpoints."""
    config = machine_config.github_config(getattr(result, "config_path", None))
    return github_origin.validate_github_endpoint_pair(
        str(config.get("api_url") or github_origin.DEFAULT_GITHUB_API_URL),
        str(config.get("web_url") or github_origin.DEFAULT_GITHUB_WEB_URL),
    )


__all__ = [
    "administration_allowed",
    "clone_web_url",
    "connection_scope",
    "connected",
    "endpoint_pair",
    "fork_ready",
    "fork_ready_from_config",
    "repository_access_url",
    "user_access_token",
    "web_url",
]
