"""Shared fixtures for GitHub App runtime advertisement tests."""

from __future__ import annotations

from pathlib import Path

from yoke_contracts.github_app_public import (
    GITHUB_APP_API_URL_ENV,
    GITHUB_APP_CLIENT_ID_ENV,
    GITHUB_APP_ID_ENV,
    GITHUB_APP_SLUG_ENV,
    GITHUB_APP_WEB_URL_ENV,
)
from yoke_core.domain.github_app_control_plane import (
    GITHUB_APP_ISSUER_ENV,
    GITHUB_APP_PRIVATE_KEY_FILE_ENV,
)
from yoke_core.domain.github_app_identity import GitHubAppIdentity


def complete_github_app_env(tmp_path: Path) -> tuple[dict[str, str], Path]:
    key = tmp_path / "github-app.pem"
    key.write_text("test-private-key", encoding="utf-8")
    key.chmod(0o600)
    return (
        {
            GITHUB_APP_ISSUER_ENV: "123456",
            GITHUB_APP_PRIVATE_KEY_FILE_ENV: str(key),
            GITHUB_APP_API_URL_ENV: "https://api.github.com",
            GITHUB_APP_WEB_URL_ENV: "https://github.com",
            GITHUB_APP_ID_ENV: "123456",
            GITHUB_APP_CLIENT_ID_ENV: "Iv23public",
            GITHUB_APP_SLUG_ENV: "yoke-development",
        },
        key,
    )


def matching_github_app_identity() -> GitHubAppIdentity:
    return GitHubAppIdentity(
        app_id=123456,
        client_id="Iv23public",
        slug="yoke-development",
    )


__all__ = ["complete_github_app_env", "matching_github_app_identity"]
