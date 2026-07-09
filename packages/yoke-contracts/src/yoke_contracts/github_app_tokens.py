"""Shared constants for GitHub App token exchanges."""

from __future__ import annotations

DEFAULT_GITHUB_WEB_BASE = "https://github.com"
GITHUB_APP_ACCEPT = "application/vnd.github+json"
GITHUB_APP_USER_AGENT = "yoke-github-app"
GITHUB_JSON_ACCEPT = "application/json"
GITHUB_OAUTH_ACCESS_TOKEN_PATH = "/login/oauth/access_token"
GITHUB_OAUTH_REFRESH_GRANT_TYPE = "refresh_token"

__all__ = [
    "DEFAULT_GITHUB_WEB_BASE",
    "GITHUB_APP_ACCEPT",
    "GITHUB_APP_USER_AGENT",
    "GITHUB_JSON_ACCEPT",
    "GITHUB_OAUTH_ACCESS_TOKEN_PATH",
    "GITHUB_OAUTH_REFRESH_GRANT_TYPE",
]
