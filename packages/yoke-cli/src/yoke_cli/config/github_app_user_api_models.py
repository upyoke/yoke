"""Validation and normalization for GitHub App discovery payloads."""

from __future__ import annotations

from typing import Any, Mapping

from yoke_contracts import (
    github_app_snapshot,
    github_installation_urls,
    github_origin,
)


class GitHubAppUserApiError(RuntimeError):
    """A live GitHub App user API request or payload failed validation."""

    def __init__(self, message: str, *, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


def normalize_installation(
    item: Mapping[str, Any],
    *,
    web_endpoint: github_origin.GitHubWebEndpoint | None,
) -> dict[str, Any]:
    account = item.get("account")
    if not isinstance(account, Mapping):
        raise GitHubAppUserApiError("GitHub installation account is missing")
    permissions = item.get("permissions")
    try:
        account_login = github_app_snapshot.user_login(
            account.get("login"),
            "installation.account.login",
        )
        app_slug = github_app_snapshot.app_slug(item.get("app_slug"))
        account_type = github_app_snapshot.account_type(account.get("type"))
        selection = github_app_snapshot.repository_selection(
            item.get("repository_selection"),
        )
        selected_permissions = github_app_snapshot.permissions(permissions)
    except github_app_snapshot.GitHubAppSnapshotError as exc:
        raise GitHubAppUserApiError(str(exc)) from exc
    installation_id = required_int(item.get("id"), "installation.id")
    normalized = {
        "installation_id": installation_id,
        "app_id": required_int(item.get("app_id"), "installation.app_id"),
        "app_slug": app_slug,
        "account_id": required_int(account.get("id"), "installation.account.id"),
        "account_login": account_login,
        "account_type": account_type,
        "repository_selection": selection,
        "suspended": bool(item.get("suspended_at")),
        "permissions": selected_permissions,
    }
    html_url = installation_html_url(
        item.get("html_url"),
        web_endpoint=web_endpoint,
        installation_id=installation_id,
        account_login=account_login,
    )
    if html_url:
        normalized["html_url"] = html_url
    return normalized


def installation_html_url(
    value: Any,
    *,
    web_endpoint: github_origin.GitHubWebEndpoint | None,
    installation_id: int,
    account_login: str,
) -> str:
    if web_endpoint is None or not isinstance(value, str):
        return ""
    try:
        return github_installation_urls.validated_settings_url(
            value,
            web_url=web_endpoint.base_url,
            installation_id=installation_id,
            account_login=account_login,
        )
    except github_origin.GitHubApiOriginError:
        return ""


def normalize_repository(
    item: Mapping[str, Any],
    *,
    installation_id: int,
) -> dict[str, Any]:
    try:
        full_name = github_app_snapshot.repository_full_name(item.get("full_name"))
        branch = github_app_snapshot.default_branch(item.get("default_branch"))
    except github_app_snapshot.GitHubAppSnapshotError as exc:
        raise GitHubAppUserApiError(str(exc)) from exc
    return {
        "repository_id": required_int(item.get("id"), "repository.id"),
        "full_name": full_name,
        "default_branch": branch,
        "private": required_bool(item.get("private"), "repository.private"),
        "installation_id": installation_id,
    }


def required_string(value: Any, label: str) -> str:
    if not isinstance(value, str):
        raise GitHubAppUserApiError(f"{label} must be a string")
    text = value.strip()
    if not text:
        raise GitHubAppUserApiError(f"{label} is required")
    return text


def required_int(value: Any, label: str) -> int:
    if isinstance(value, bool):
        raise GitHubAppUserApiError(f"{label} must be an integer")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise GitHubAppUserApiError(f"{label} must be an integer") from exc
    if parsed <= 0:
        raise GitHubAppUserApiError(f"{label} must be positive")
    return parsed


def required_bool(value: Any, label: str) -> bool:
    if not isinstance(value, bool):
        raise GitHubAppUserApiError(f"{label} must be a boolean")
    return value


__all__ = [
    "GitHubAppUserApiError",
    "normalize_installation",
    "normalize_repository",
    "required_int",
    "required_string",
]
