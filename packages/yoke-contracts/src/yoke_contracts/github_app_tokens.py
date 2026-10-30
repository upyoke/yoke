"""Shared constants for GitHub App token exchanges."""

from __future__ import annotations

from typing import NamedTuple, Mapping, Any

if __package__:
    from yoke_contracts.github_origin import DEFAULT_GITHUB_WEB_URL
else:  # pragma: no cover - copied helper always uses its immutable sibling
    from _yoke_github_origin import DEFAULT_GITHUB_WEB_URL  # type: ignore

DEFAULT_GITHUB_WEB_BASE = DEFAULT_GITHUB_WEB_URL
GITHUB_API_VERSION = "2022-11-28"
GITHUB_APP_ACCEPT = "application/vnd.github+json"
GITHUB_CAPABILITY_TYPE = "github"
GITHUB_AUTH_KIND_USER_AUTHORIZATION = "github_app_user_authorization"
GITHUB_PROFILE_SOURCE_SERVICE = "service"
GITHUB_PROFILE_SOURCE_LOCAL_EXPLICIT = "local_explicit"
GITHUB_PROFILE_SOURCE_LOCAL_PRODUCT = "local_product"


class LocalProductGitHubAppProfile(NamedTuple):
    """Exact immutable public identity compiled into a Yoke release."""

    client_id: str
    app_slug: str
    app_id: int
    api_url: str
    web_url: str


# Release-owned, nonsecret identity for the baseline GitHub App used by a
# local Yoke universe.  Registration values land here as one atomic profile;
# ``None`` keeps pre-registration builds fail-closed.  Runtime environment
# variables never override this authority.
BUNDLED_LOCAL_PRODUCT_GITHUB_APP_PROFILE: LocalProductGitHubAppProfile | None = (
    LocalProductGitHubAppProfile(
        client_id="Iv23liSQ2ATZYGZtbof0",
        app_slug="yoke-by-upyoke-com",
        app_id=4_276_191,
        api_url="https://api.github.com",
        web_url="https://github.com",
    )
)


def local_product_profile_values() -> dict[str, str | int] | None:
    """Return a fresh exact-field mapping for validators and helper bundles."""

    profile = BUNDLED_LOCAL_PRODUCT_GITHUB_APP_PROFILE
    if not isinstance(profile, LocalProductGitHubAppProfile):
        return None
    return {
        "client_id": profile.client_id,
        "app_slug": profile.app_slug,
        "app_id": profile.app_id,
        "api_url": profile.api_url,
        "web_url": profile.web_url,
    }


GITHUB_PROFILE_IDENTITY_FIELDS = (
    "client_id",
    "app_slug",
    "app_id",
    "api_url",
    "web_url",
    "profile_source",
    "profile_service_api_url",
)
YOKE_ENV_OVERRIDE_NAME = "YOKE_ENV"
GITHUB_CONNECTIONS_KEY = "connection_github"


def github_connection_label(config: Mapping[str, Any], env: str) -> str:
    """Use the HTTPS sibling for a database-admin connection."""
    label = str(env or "").strip()
    connections = config.get("connections") or {}
    base = label.removesuffix("-db-admin")
    sibling = connections.get(base) if isinstance(connections, Mapping) else None
    if (
        base != label
        and isinstance(sibling, Mapping)
        and sibling.get("transport") == "https"
    ):
        return base
    return label


def connection_github(config: Mapping[str, Any], env: str) -> dict[str, Any]:
    """Read only the selected slot, or the unmigrated legacy record."""
    if GITHUB_CONNECTIONS_KEY not in config:
        raw = config.get("github")
    else:
        slots = config.get(GITHUB_CONNECTIONS_KEY)
        raw = (
            slots.get(github_connection_label(config, env))
            if isinstance(slots, Mapping)
            else None
        )
    return dict(raw) if isinstance(raw, Mapping) else {}


def github_configurations(config: Mapping[str, Any]) -> dict[str, Any]:
    """Enumerate stored records for validation, cleanup and presence facts."""
    legacy = connection_github(
        {k: v for k, v in config.items() if k != GITHUB_CONNECTIONS_KEY}, ""
    )
    entries = {"github": legacy} if legacy else {}
    slots = config.get(GITHUB_CONNECTIONS_KEY)
    if isinstance(slots, Mapping):
        entries.update(
            {
                f"{GITHUB_CONNECTIONS_KEY}.{label}": value
                for label, value in slots.items()
            }
        )
    return entries


GITHUB_APP_USER_AGENT = "yoke-github-app"
GITHUB_JSON_ACCEPT = "application/json"
GITHUB_OAUTH_DEVICE_CODE_PATH = "/login/device/code"
GITHUB_OAUTH_DEVICE_GRANT_TYPE = "urn:ietf:params:oauth:grant-type:device_code"
GITHUB_OAUTH_ACCESS_TOKEN_PATH = "/login/oauth/access_token"
GITHUB_OAUTH_REFRESH_GRANT_TYPE = "refresh_token"
GITHUB_OAUTH_SLOW_DOWN_SECONDS = 5
GITHUB_OAUTH_RESPONSE_MAX_BYTES = 64 * 1024
GITHUB_API_RESPONSE_MAX_BYTES = 4 * 1024 * 1024
GITHUB_OAUTH_DEVICE_CODE_MAX_SECONDS = 15 * 60
GITHUB_OAUTH_POLL_INTERVAL_MAX_SECONDS = 60
GITHUB_APP_USER_ACCESS_TOKEN_MAX_SECONDS = 24 * 60 * 60
GITHUB_APP_USER_REFRESH_TOKEN_MAX_SECONDS = 366 * 24 * 60 * 60
# A stored access token is served until this much of its life remains, so a
# git command that starts inside the margin still finishes with a token the
# remote accepts. Refreshing rotates the authorization and revokes whatever
# token another process is already carrying, so the margin is the whole
# reason a busy machine can share one token instead of racing for new ones.
GITHUB_APP_USER_ACCESS_TOKEN_REFRESH_MARGIN_SECONDS = 120
GITHUB_APP_USER_AUTH_CONFIGURATION_HINT = (
    "In the GitHub App settings, enable Device Flow and "
    "'Expire user authorization tokens', then reconnect GitHub."
)

__all__ = [
    "GITHUB_CONNECTIONS_KEY",
    "github_connection_label",
    "connection_github",
    "github_configurations",
    "DEFAULT_GITHUB_WEB_BASE",
    "GITHUB_API_VERSION",
    "GITHUB_APP_ACCEPT",
    "GITHUB_CAPABILITY_TYPE",
    "GITHUB_APP_USER_AGENT",
    "GITHUB_AUTH_KIND_USER_AUTHORIZATION",
    "GITHUB_PROFILE_SOURCE_LOCAL_EXPLICIT",
    "GITHUB_PROFILE_SOURCE_LOCAL_PRODUCT",
    "GITHUB_PROFILE_SOURCE_SERVICE",
    "BUNDLED_LOCAL_PRODUCT_GITHUB_APP_PROFILE",
    "LocalProductGitHubAppProfile",
    "local_product_profile_values",
    "GITHUB_PROFILE_IDENTITY_FIELDS",
    "YOKE_ENV_OVERRIDE_NAME",
    "GITHUB_JSON_ACCEPT",
    "GITHUB_OAUTH_DEVICE_CODE_PATH",
    "GITHUB_OAUTH_DEVICE_GRANT_TYPE",
    "GITHUB_OAUTH_ACCESS_TOKEN_PATH",
    "GITHUB_OAUTH_REFRESH_GRANT_TYPE",
    "GITHUB_OAUTH_SLOW_DOWN_SECONDS",
    "GITHUB_OAUTH_RESPONSE_MAX_BYTES",
    "GITHUB_OAUTH_DEVICE_CODE_MAX_SECONDS",
    "GITHUB_OAUTH_POLL_INTERVAL_MAX_SECONDS",
    "GITHUB_API_RESPONSE_MAX_BYTES",
    "GITHUB_APP_USER_ACCESS_TOKEN_MAX_SECONDS",
    "GITHUB_APP_USER_REFRESH_TOKEN_MAX_SECONDS",
    "GITHUB_APP_USER_ACCESS_TOKEN_REFRESH_MARGIN_SECONDS",
    "GITHUB_APP_USER_AUTH_CONFIGURATION_HINT",
]
