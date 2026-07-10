"""Shared constants for GitHub App token exchanges."""

from __future__ import annotations

try:
    from yoke_contracts.github_origin import DEFAULT_GITHUB_WEB_URL
except ModuleNotFoundError:  # pragma: no cover - copied source-dev helper
    from _yoke_github_origin import DEFAULT_GITHUB_WEB_URL  # type: ignore

DEFAULT_GITHUB_WEB_BASE = DEFAULT_GITHUB_WEB_URL
GITHUB_API_VERSION = "2022-11-28"
GITHUB_APP_ACCEPT = "application/vnd.github+json"
GITHUB_CAPABILITY_TYPE = "github"
GITHUB_AUTH_KIND_USER_AUTHORIZATION = "github_app_user_authorization"
GITHUB_APP_USER_AGENT = "yoke-github-app"
GITHUB_JSON_ACCEPT = "application/json"
GITHUB_OAUTH_DEVICE_CODE_PATH = "/login/device/code"
GITHUB_OAUTH_DEVICE_GRANT_TYPE = (
    "urn:ietf:params:oauth:grant-type:device_code"
)
GITHUB_OAUTH_ACCESS_TOKEN_PATH = "/login/oauth/access_token"
GITHUB_OAUTH_REFRESH_GRANT_TYPE = "refresh_token"
GITHUB_OAUTH_SLOW_DOWN_SECONDS = 5
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
    "GITHUB_JSON_ACCEPT",
    "GITHUB_OAUTH_DEVICE_CODE_PATH",
    "GITHUB_OAUTH_DEVICE_GRANT_TYPE",
    "GITHUB_OAUTH_ACCESS_TOKEN_PATH",
    "GITHUB_OAUTH_REFRESH_GRANT_TYPE",
    "GITHUB_OAUTH_SLOW_DOWN_SECONDS",
    "GITHUB_APP_USER_AUTH_CONFIGURATION_HINT",
]
