"""Shared constants for GitHub App token exchanges."""

from __future__ import annotations

from typing import NamedTuple

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
    "client_id", "app_slug", "app_id", "api_url", "web_url",
    "profile_source", "profile_service_api_url",
)
YOKE_ENV_OVERRIDE_NAME = "YOKE_ENV"
GITHUB_APP_USER_AGENT = "yoke-github-app"
GITHUB_JSON_ACCEPT = "application/json"
GITHUB_OAUTH_DEVICE_CODE_PATH = "/login/device/code"
GITHUB_OAUTH_DEVICE_GRANT_TYPE = (
    "urn:ietf:params:oauth:grant-type:device_code"
)
GITHUB_OAUTH_ACCESS_TOKEN_PATH = "/login/oauth/access_token"
GITHUB_OAUTH_REFRESH_GRANT_TYPE = "refresh_token"
GITHUB_OAUTH_SLOW_DOWN_SECONDS = 5
GITHUB_OAUTH_RESPONSE_MAX_BYTES = 64 * 1024
GITHUB_API_RESPONSE_MAX_BYTES = 4 * 1024 * 1024
GITHUB_OAUTH_DEVICE_CODE_MAX_SECONDS = 15 * 60
GITHUB_OAUTH_POLL_INTERVAL_MAX_SECONDS = 60
GITHUB_APP_USER_ACCESS_TOKEN_MAX_SECONDS = 24 * 60 * 60
GITHUB_APP_USER_REFRESH_TOKEN_MAX_SECONDS = 366 * 24 * 60 * 60
GITHUB_APP_USER_AUTH_CONFIGURATION_HINT = (
    "In the GitHub App settings, enable Device Flow and "
    "'Expire user authorization tokens', then reconnect GitHub."
)

__all__ = [
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
    "GITHUB_APP_USER_AUTH_CONFIGURATION_HINT",
]
