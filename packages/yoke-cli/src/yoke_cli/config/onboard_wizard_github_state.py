"""GitHub App connection helpers for onboarding wizard state."""

from __future__ import annotations

from typing import Any

from yoke_contracts import github_installation_urls, github_origin
from yoke_cli.config import github_local_user_access
from yoke_cli.config import machine_config
from yoke_cli.config import onboard_destinations
from yoke_cli.config import onboard_machine_github


def ready_from_report(report: Any) -> bool:
    """True when a ``yoke github status`` report (or stored copy) is ready."""

    return isinstance(report, dict) and bool(report.get("ready"))


def connected(result: Any) -> bool:
    """Whether this run proved usable machine GitHub authorization.

    Matches ``yoke github status --json`` ``ready``: merge-path user
    authorization and App installation must both be ok. A later wizard
    step does not substitute for that proof.
    """
    verification = getattr(result, "machine_github_verification", None)
    if not isinstance(verification, dict):
        return False
    return bool(
        getattr(result, "machine_github_choice", None)
        == onboard_machine_github.CHOICE_CONNECT
        and ready_from_report(verification)
        and verification.get("ok")
        and verification.get("configured") is not False
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
        getattr(result, "destination", None) == onboard_destinations.DESTINATION_LOCAL
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
            str(installation.get("account_login") or "").casefold() != selected_owner
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
            pass
        installation_id = installation.get("installation_id")
        login = str(installation.get("account_login") or "")
        try:
            url = endpoint.installation_settings_url(installation_id)
            if str(installation.get("account_type") or "").casefold() == "organization":
                url = endpoint.web.url(
                    f"/organizations/{login}/settings/installations/{installation_id}"
                )
            return github_installation_urls.validated_settings_url(
                url,
                web_url=endpoint.web.base_url,
                installation_id=installation_id,
                account_login=login,
            )
        except github_origin.GitHubApiOriginError:
            continue
    raise github_origin.GitHubApiOriginError(
        "github_installation_settings_unavailable: no valid installation identity "
        "for this owner. Reconnect the Yoke GitHub App for this owner, then check access again."
    )


def administration_allowed(result: Any) -> bool:
    """Whether the selected owner has a live optional Administration grant."""
    config = machine_config.github_config(getattr(result, "config_path", None))
    try:
        if (
            github_origin.validate_github_endpoint_pair(
                str(config.get("api_url") or github_origin.DEFAULT_GITHUB_API_URL),
                str(config.get("web_url") or github_origin.DEFAULT_GITHUB_WEB_URL),
            ).deployment_kind
            != "github_cloud"
        ):
            return False
    except github_origin.GitHubApiOriginError:
        return False
    owner = str(getattr(result, "project_publish_owner", None) or "").casefold()
    return any(
        isinstance(row, dict)
        and isinstance(row.get("permissions"), dict)
        and str(row.get("account_login") or "").casefold() == owner
        and not row.get("suspended")
        and row.get("repository_selection") == "all"
        and row["permissions"].get("administration") == "write"
        for row in config.get("installations") or []
    )


def fork_ready(result: Any, remote_url: str | None) -> bool:
    """Whether App installation topology satisfies GitHub's fork API rules."""

    return not fork_unavailable_reason(result, remote_url)


def fork_unavailable_reason(result: Any, remote_url: str | None) -> str:
    from yoke_cli.config import github_fork_access

    if not connected(result):
        return github_fork_access.UNVERIFIED
    config = machine_config.github_config(getattr(result, "config_path", None))
    return github_fork_access.unavailable_reason(config, remote_url)


def fork_ready_from_config(
    config: dict[str, Any],
    remote_url: str | None,
) -> bool:
    """Whether cached topology satisfies GitHub's fork endpoint permissions."""
    from yoke_cli.config import github_fork_access

    return not github_fork_access.unavailable_reason(config, remote_url)


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
    "fork_unavailable_reason",
    "fork_ready_from_config",
    "ready_from_report",
    "repository_access_url",
    "user_access_token",
    "web_url",
]
