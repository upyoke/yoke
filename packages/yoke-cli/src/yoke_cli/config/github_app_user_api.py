"""Read-only GitHub App user APIs for local installation discovery."""

from __future__ import annotations

import json
from typing import Any, Callable, Mapping
import urllib.error
import urllib.parse
import urllib.request

from yoke_contracts import github_app_tokens, github_origin

MAX_PAGINATION_PAGES = 100


class GitHubAppUserApiError(RuntimeError):
    """A live GitHub App user API request failed."""

    def __init__(self, message: str, *, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_urlopen = urllib.request.build_opener(_NoRedirectHandler()).open


def discover_access(
    *,
    api_url: str,
    access_token: str,
    opener: Callable[..., Any] | None = None,
    timeout_seconds: float = 30.0,
) -> dict[str, Any]:
    """Return the signed-in user, App installations, and visible repos."""
    base = validated_api_url(api_url)
    token = _required_string(access_token, "access_token")
    user = _request_json(
        f"{base}/user", token=token, opener=opener,
        timeout_seconds=timeout_seconds,
    )
    installations = _paginate(
        f"{base}/user/installations", collection_key="installations",
        token=token, opener=opener, timeout_seconds=timeout_seconds,
    )
    normalized_installations = [
        _installation(item) for item in installations
        if isinstance(item, Mapping)
    ]
    repositories: list[dict[str, Any]] = []
    for installation in normalized_installations:
        if installation["suspended"]:
            continue
        installation_id = installation["installation_id"]
        rows = _paginate(
            f"{base}/user/installations/{installation_id}/repositories",
            collection_key="repositories", token=token, opener=opener,
            timeout_seconds=timeout_seconds,
        )
        repositories.extend(
            _repository(item, installation_id=installation_id)
            for item in rows if isinstance(item, Mapping)
        )
    return {
        "user": {
            "id": _required_int(user.get("id"), "user.id"),
            "login": _required_string(user.get("login"), "user.login"),
        },
        "installations": normalized_installations,
        "repositories": repositories,
    }


def validated_api_url(value: str) -> str:
    try:
        return github_origin.validate_github_api_endpoint(value).base_url
    except github_origin.GitHubApiOriginError as exc:
        raise GitHubAppUserApiError(str(exc)) from exc


def _paginate(
    url: str,
    *,
    collection_key: str,
    token: str,
    opener: Callable[..., Any] | None,
    timeout_seconds: float,
) -> list[Any]:
    rows: list[Any] = []
    page = 1
    while page <= MAX_PAGINATION_PAGES:
        separator = "&" if "?" in url else "?"
        payload = _request_json(
            f"{url}{separator}per_page=100&page={page}", token=token,
            opener=opener, timeout_seconds=timeout_seconds,
        )
        batch = payload.get(collection_key)
        if not isinstance(batch, list):
            raise GitHubAppUserApiError(
                f"GitHub response {collection_key} must be a list"
            )
        rows.extend(batch)
        if len(batch) < 100:
            return rows
        page += 1
    raise GitHubAppUserApiError(
        f"GitHub {collection_key} listing exceeded {MAX_PAGINATION_PAGES} pages"
    )


def _request_json(
    url: str,
    *,
    token: str,
    opener: Callable[..., Any] | None,
    timeout_seconds: float,
) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": github_app_tokens.GITHUB_APP_ACCEPT,
            "Authorization": f"Bearer {token}",
            "User-Agent": github_app_tokens.GITHUB_APP_USER_AGENT,
            "X-GitHub-Api-Version": github_app_tokens.GITHUB_API_VERSION,
        },
        method="GET",
    )
    try:
        with (opener or _urlopen)(request, timeout=timeout_seconds) as response:
            raw = response.read()
    except urllib.error.HTTPError as exc:
        raise GitHubAppUserApiError(
            f"GitHub user API failed with HTTP {exc.code}", status=exc.code
        ) from exc
    except urllib.error.URLError as exc:
        raise GitHubAppUserApiError(
            f"GitHub user API failed: {exc.reason}"
        ) from exc
    try:
        payload = json.loads(raw.decode("utf-8") or "{}")
    except ValueError as exc:
        raise GitHubAppUserApiError("GitHub user API response is not JSON") from exc
    if not isinstance(payload, dict):
        raise GitHubAppUserApiError("GitHub user API response must be an object")
    return payload


def _installation(item: Mapping[str, Any]) -> dict[str, Any]:
    account = item.get("account")
    if not isinstance(account, Mapping):
        raise GitHubAppUserApiError("GitHub installation account is missing")
    suspended = bool(item.get("suspended_at"))
    permissions = item.get("permissions")
    return {
        "installation_id": _required_int(item.get("id"), "installation.id"),
        "account_id": _required_int(account.get("id"), "installation.account.id"),
        "account_login": _required_string(
            account.get("login"), "installation.account.login"
        ),
        "account_type": str(account.get("type") or ""),
        "repository_selection": str(item.get("repository_selection") or "selected"),
        "suspended": suspended,
        "permissions": dict(permissions) if isinstance(permissions, Mapping) else {},
    }


def _repository(
    item: Mapping[str, Any], *, installation_id: int,
) -> dict[str, Any]:
    return {
        "repository_id": _required_int(item.get("id"), "repository.id"),
        "full_name": _required_string(item.get("full_name"), "repository.full_name"),
        "default_branch": str(item.get("default_branch") or ""),
        "installation_id": installation_id,
    }


def _required_string(value: Any, label: str) -> str:
    if not isinstance(value, str):
        raise GitHubAppUserApiError(f"{label} must be a string")
    text = value.strip()
    if not text:
        raise GitHubAppUserApiError(f"{label} is required")
    return text


def _required_int(value: Any, label: str) -> int:
    if isinstance(value, bool):
        raise GitHubAppUserApiError(f"{label} must be an integer")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise GitHubAppUserApiError(f"{label} must be an integer") from exc
    if parsed <= 0:
        raise GitHubAppUserApiError(f"{label} must be positive")
    return parsed


__all__ = [
    "GitHubAppUserApiError",
    "discover_access",
    "validated_api_url",
]
