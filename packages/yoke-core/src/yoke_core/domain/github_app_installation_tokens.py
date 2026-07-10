"""Mint and cache GitHub App installation tokens."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import json
from typing import Any, Callable, Iterable, Mapping
import urllib.error
import urllib.request

from yoke_contracts import github_app_tokens as token_contract

from yoke_core.domain import gh_rest_transport
from yoke_contracts.github_origin import (
    GitHubApiOriginError,
    validate_github_api_endpoint,
)
from yoke_core.domain.github_api_transport import open_same_origin
from yoke_core.domain.github_app_jwt import generate_app_jwt
from yoke_core.domain.github_app_token_models import (
    GitHubAppTokenError,
    GitHubAppTokenResponseError,
    InstallationToken,
    parse_github_datetime,
    parse_json_object,
    require_nonempty_string,
    utc_now,
)

@dataclass(frozen=True)
class InstallationTokenCacheKey:
    api_url: str
    issuer: str
    installation_id: int
    repository_ids: tuple[int, ...] = ()
    repositories: tuple[str, ...] = ()
    permissions: tuple[tuple[str, str], ...] = ()


@dataclass
class InstallationTokenCache:
    """In-memory installation-token cache bounded by GitHub's expiry."""

    _tokens: dict[InstallationTokenCacheKey, InstallationToken] = field(
        default_factory=dict
    )

    def get_or_mint(
        self,
        *,
        issuer: str | int,
        private_key_pem: str | bytes,
        installation_id: int,
        api_url: str = gh_rest_transport.GITHUB_API_BASE,
        repository_ids: Iterable[int] | None = None,
        repositories: Iterable[str] | None = None,
        permissions: Mapping[str, str] | None = None,
        now: datetime | None = None,
        opener: Callable[..., Any] | None = None,
        timeout_seconds: float = 30.0,
        refresh_skew_seconds: int = 60,
    ) -> InstallationToken:
        selected_now = now or utc_now()
        selected_installation_id = _normalize_installation_id(installation_id)
        normalized = _normalize_restrictions(
            repository_ids=repository_ids,
            repositories=repositories,
            permissions=permissions,
        )
        key = _cache_key(
            issuer=issuer,
            installation_id=selected_installation_id,
            api_url=api_url,
            normalized=normalized,
        )
        cached = self._tokens.get(key)
        if cached and cached.usable_at(selected_now, skew_seconds=refresh_skew_seconds):
            return cached
        minted = mint_installation_token(
            issuer=issuer,
            private_key_pem=private_key_pem,
            installation_id=selected_installation_id,
            api_url=api_url,
            repository_ids=normalized.repository_ids,
            repositories=normalized.repositories,
            permissions=normalized.permissions,
            now=selected_now,
            opener=opener,
            timeout_seconds=timeout_seconds,
        )
        self._tokens[key] = minted
        return minted

    def clear(self) -> None:
        self._tokens.clear()


def mint_installation_token(
    *,
    issuer: str | int,
    private_key_pem: str | bytes,
    installation_id: int,
    api_url: str = gh_rest_transport.GITHUB_API_BASE,
    repository_ids: Iterable[int] | None = None,
    repositories: Iterable[str] | None = None,
    permissions: Mapping[str, str] | None = None,
    now: datetime | None = None,
    opener: Callable[..., Any] | None = None,
    timeout_seconds: float = 30.0,
) -> InstallationToken:
    """Mint a short-lived bearer token for a GitHub App installation."""

    normalized = _normalize_restrictions(
        repository_ids=repository_ids,
        repositories=repositories,
        permissions=permissions,
    )
    selected_installation_id = _normalize_installation_id(installation_id)
    selected_now = now or utc_now()
    app_jwt = generate_app_jwt(
        issuer=issuer,
        private_key_pem=private_key_pem,
        now=selected_now,
    )
    body: dict[str, Any] = {}
    if normalized.repository_ids:
        body["repository_ids"] = list(normalized.repository_ids)
    if normalized.repositories:
        body["repositories"] = list(normalized.repositories)
    if normalized.permissions:
        body["permissions"] = dict(normalized.permissions)
    payload = _issue_token_request(
        api_url=api_url,
        installation_id=selected_installation_id,
        app_jwt=app_jwt,
        body=body,
        opener=opener,
        timeout_seconds=timeout_seconds,
    )
    return _parse_installation_token(payload)


def _issue_token_request(
    *,
    api_url: str,
    installation_id: int,
    app_jwt: str,
    body: Mapping[str, Any],
    opener: Callable[..., Any] | None,
    timeout_seconds: float,
) -> dict[str, Any]:
    endpoint = _validated_endpoint(api_url)
    selected_url = (
        f"{endpoint.base_url}/app/installations/"
        f"{installation_id}/access_tokens"
    )
    request = urllib.request.Request(
        selected_url,
        data=json.dumps(dict(body)).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {app_jwt}",
            "Accept": token_contract.GITHUB_APP_ACCEPT,
            "Content-Type": "application/json",
            "X-GitHub-Api-Version": gh_rest_transport.GITHUB_API_VERSION,
            "User-Agent": token_contract.GITHUB_APP_USER_AGENT,
        },
        method="POST",
    )
    try:
        with open_same_origin(
            request,
            endpoint=endpoint,
            timeout_seconds=timeout_seconds,
            opener=opener,
        ) as response:
            return parse_json_object(response.read(), "GitHub installation token")
    except urllib.error.HTTPError as exc:
        body_text = _read_error_body(exc)
        raise GitHubAppTokenResponseError(
            "GitHub installation token request failed",
            status=exc.code,
            body=body_text,
        ) from exc
    except urllib.error.URLError as exc:
        raise GitHubAppTokenError(
            f"GitHub installation token request failed: {exc.reason}"
        ) from exc
    except GitHubApiOriginError as exc:
        raise GitHubAppTokenError(str(exc)) from exc


def _parse_installation_token(payload: Mapping[str, Any]) -> InstallationToken:
    raw_permissions = payload.get("permissions")
    permissions = (
        {str(key): str(value) for key, value in raw_permissions.items()}
        if isinstance(raw_permissions, Mapping)
        else {}
    )
    repositories = tuple(
        str(item.get("full_name") or "")
        for item in payload.get("repositories") or []
        if isinstance(item, Mapping) and str(item.get("full_name") or "")
    )
    return InstallationToken(
        token=require_nonempty_string(payload.get("token"), "installation token"),
        expires_at=parse_github_datetime(payload.get("expires_at"), "expires_at"),
        permissions=permissions,
        repository_selection=str(payload.get("repository_selection") or ""),
        repositories=repositories,
    )


@dataclass(frozen=True)
class _NormalizedRestrictions:
    repository_ids: tuple[int, ...]
    repositories: tuple[str, ...]
    permissions: dict[str, str]


def _normalize_restrictions(
    *,
    repository_ids: Iterable[int] | None,
    repositories: Iterable[str] | None,
    permissions: Mapping[str, str] | None,
) -> _NormalizedRestrictions:
    normalized_ids = _normalize_repository_ids(repository_ids)
    normalized_repositories = _normalize_repositories(repositories)
    if normalized_ids and normalized_repositories:
        raise GitHubAppTokenError(
            "restrict installation tokens by repository ids or repository names, not both"
        )
    return _NormalizedRestrictions(
        repository_ids=normalized_ids,
        repositories=normalized_repositories,
        permissions=_normalize_permissions(permissions),
    )


def _normalize_repository_ids(values: Iterable[int] | None) -> tuple[int, ...]:
    if values is None:
        return ()
    normalized: list[int] = []
    for value in values:
        if isinstance(value, bool):
            raise GitHubAppTokenError("repository_ids must contain integers")
        try:
            parsed = int(value)
        except (TypeError, ValueError) as exc:
            raise GitHubAppTokenError("repository_ids must contain integers") from exc
        if parsed <= 0:
            raise GitHubAppTokenError("repository_ids must contain positive integers")
        normalized.append(parsed)
    return tuple(normalized)


def _normalize_repositories(values: Iterable[str] | None) -> tuple[str, ...]:
    if values is None:
        return ()
    normalized: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if not text:
            raise GitHubAppTokenError("repositories must contain non-empty names")
        if "/" in text:
            raise GitHubAppTokenError(
                "repositories must contain bare repository names, not owner/name"
            )
        normalized.append(text)
    if not normalized:
        return ()
    return tuple(normalized)


def _normalize_installation_id(value: int) -> int:
    if isinstance(value, bool):
        raise GitHubAppTokenError("installation_id must be a positive integer")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise GitHubAppTokenError("installation_id must be a positive integer") from exc
    if parsed <= 0:
        raise GitHubAppTokenError("installation_id must be a positive integer")
    return parsed


def _normalize_permissions(values: Mapping[str, str] | None) -> dict[str, str]:
    if not values:
        return {}
    normalized: dict[str, str] = {}
    for key, value in values.items():
        permission = str(key or "").strip()
        access = str(value or "").strip()
        if not permission or not access:
            raise GitHubAppTokenError("permissions must contain non-empty strings")
        normalized[permission] = access
    return normalized


def _cache_key(
    *,
    issuer: str | int,
    installation_id: int,
    api_url: str,
    normalized: _NormalizedRestrictions,
) -> InstallationTokenCacheKey:
    return InstallationTokenCacheKey(
        api_url=_clean_api_url(api_url),
        issuer=require_nonempty_string(issuer, "GitHub App JWT issuer"),
        installation_id=installation_id,
        repository_ids=tuple(sorted(normalized.repository_ids)),
        repositories=tuple(sorted(normalized.repositories)),
        permissions=tuple(sorted(normalized.permissions.items())),
    )


def _clean_api_url(api_url: str) -> str:
    return _validated_endpoint(api_url).base_url


def _validated_endpoint(api_url: str):
    try:
        return validate_github_api_endpoint(api_url)
    except GitHubApiOriginError as exc:
        raise GitHubAppTokenError(str(exc)) from exc


def _read_error_body(exc: urllib.error.HTTPError) -> str:
    try:
        return exc.read().decode("utf-8", errors="replace")
    except Exception:
        return ""


__all__ = [
    "InstallationTokenCache",
    "InstallationTokenCacheKey",
    "mint_installation_token",
]
