"""Verify project binding intent with a transient GitHub App user token."""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any, Callable, Mapping
import urllib.error
import urllib.parse
import urllib.request

from yoke_contracts import github_app_tokens as token_contract

from yoke_core.domain import gh_rest_transport
from yoke_contracts.github_origin import (
    DEFAULT_GITHUB_API_URL,
    GitHubApiEndpoint,
    GitHubApiOriginError,
    validate_github_api_endpoint,
)
from yoke_core.domain.github_api_transport import open_same_origin
from yoke_core.domain.github_app_control_plane import (
    GitHubAppControlPlaneConfigError,
    load_github_app_endpoint,
)
from yoke_core.domain.github_app_dispatch_context import LOCAL_API_ENDPOINT
from yoke_core.domain.project_github_binding_payload import normalize_github_repo


class GitHubUserVerificationError(ValueError):
    """Raised when a user token cannot prove the requested binding intent."""


@dataclass(frozen=True)
class VerifiedProjectGitHubBinding:
    installation_id: str
    account_id: str
    account_login: str
    account_type: str
    repository_selection: str
    permissions: Mapping[str, str]
    repository_id: str
    github_repo: str
    default_branch: str
    installation_status: str = "active"
    api_url: str = DEFAULT_GITHUB_API_URL


def verify_project_github_binding(
    *,
    installation_id: str | int,
    repository_id: str | int,
    expected_github_repo: str,
    expected_api_url: str,
    github_user_access_token: str,
    endpoint: GitHubApiEndpoint | None = None,
    opener: Callable[..., Any] | None = None,
    timeout_seconds: float = 30.0,
) -> VerifiedProjectGitHubBinding:
    """Canonicalize a binding using GitHub responses, never caller metadata."""
    selected_installation_id = _positive_id(installation_id, "installation_id")
    selected_repository_id = _positive_id(repository_id, "repository_id")
    expected_repo = normalize_github_repo(expected_github_repo)
    if not expected_repo:
        raise GitHubUserVerificationError(
            "github_repo must be the expected GitHub owner/repo"
        )
    access_token = str(github_user_access_token or "").strip()
    if not access_token:
        raise GitHubUserVerificationError("github_user_access_token is required")
    try:
        selected_endpoint = (
            endpoint or LOCAL_API_ENDPOINT.get() or load_github_app_endpoint()
        )
    except GitHubAppControlPlaneConfigError as exc:
        raise GitHubUserVerificationError(str(exc)) from exc
    expected_api_url_clean = str(expected_api_url or "").strip()
    if not expected_api_url_clean:
        raise GitHubUserVerificationError("expected_api_url is required")
    try:
        expected_endpoint = validate_github_api_endpoint(expected_api_url_clean)
    except GitHubApiOriginError as exc:
        raise GitHubUserVerificationError(str(exc)) from exc
    if expected_endpoint.base_url != selected_endpoint.base_url:
        raise GitHubUserVerificationError(
            "GitHub authorization API does not match the configured control-plane "
            "or local API endpoint"
        )

    user = _get_json(
        selected_endpoint,
        "/user",
        token=access_token,
        opener=opener,
        timeout_seconds=timeout_seconds,
    )
    _required_id(user.get("id"), "authenticated GitHub user id")
    _required_text(user.get("login"), "authenticated GitHub user login")

    installation = _find_paginated(
        selected_endpoint,
        "/user/installations",
        collection_key="installations",
        selected_id=selected_installation_id,
        token=access_token,
        opener=opener,
        timeout_seconds=timeout_seconds,
    )
    if installation is None:
        raise GitHubUserVerificationError(
            "the signed-in GitHub user cannot access the requested App installation"
        )
    installation_status = (
        "suspended" if installation.get("suspended_at") else "active"
    )
    account = installation.get("account")
    if not isinstance(account, Mapping):
        raise GitHubUserVerificationError("GitHub installation account metadata is missing")
    account_id = _required_id(account.get("id"), "installation account id")
    account_login = _required_text(account.get("login"), "installation account login")
    account_type = _required_text(account.get("type"), "installation account type")

    repository = _find_paginated(
        selected_endpoint,
        f"/user/installations/{selected_installation_id}/repositories",
        collection_key="repositories",
        selected_id=selected_repository_id,
        token=access_token,
        opener=opener,
        timeout_seconds=timeout_seconds,
    )
    if repository is None:
        raise GitHubUserVerificationError(
            "the requested repository is not available to this App installation"
        )
    canonical_repo = str(repository.get("full_name") or "").strip().strip("/")
    normalized_canonical_repo = normalize_github_repo(canonical_repo)
    if not normalized_canonical_repo:
        raise GitHubUserVerificationError("GitHub repository full_name is missing")
    if normalized_canonical_repo.casefold() != expected_repo.casefold():
        raise GitHubUserVerificationError(
            f"repository id {selected_repository_id} resolves to {canonical_repo}, "
            f"not {expected_repo}"
        )
    owner = repository.get("owner")
    if isinstance(owner, Mapping) and owner.get("id") is not None:
        repository_owner_id = _required_id(owner.get("id"), "repository owner id")
        if repository_owner_id != account_id:
            raise GitHubUserVerificationError(
                "repository owner does not match the App installation account"
            )

    raw_permissions = installation.get("permissions")
    permissions = (
        {
            str(key): str(value)
            for key, value in raw_permissions.items()
            if str(key).strip() and str(value).strip()
        }
        if isinstance(raw_permissions, Mapping)
        else {}
    )
    if not permissions:
        raise GitHubUserVerificationError(
            "GitHub installation permission metadata is missing"
        )
    repository_selection = str(
        installation.get("repository_selection") or ""
    ).strip()
    if repository_selection not in {"all", "selected"}:
        raise GitHubUserVerificationError(
            "GitHub installation repository_selection is invalid"
        )
    return VerifiedProjectGitHubBinding(
        installation_id=str(selected_installation_id),
        account_id=str(account_id),
        account_login=account_login,
        account_type=account_type,
        repository_selection=repository_selection,
        permissions=permissions,
        repository_id=str(selected_repository_id),
        github_repo=canonical_repo,
        default_branch=_required_text(
            repository.get("default_branch"), "repository default branch",
        ),
        installation_status=installation_status,
        api_url=selected_endpoint.base_url,
    )


def _find_paginated(
    endpoint: GitHubApiEndpoint,
    path: str,
    *,
    collection_key: str,
    selected_id: int,
    token: str,
    opener: Callable[..., Any] | None,
    timeout_seconds: float,
) -> Mapping[str, Any] | None:
    per_page = 100
    for page in range(1, 101):
        query = urllib.parse.urlencode({"per_page": per_page, "page": page})
        payload = _get_json(
            endpoint,
            f"{path}?{query}",
            token=token,
            opener=opener,
            timeout_seconds=timeout_seconds,
        )
        raw_items = payload.get(collection_key)
        if not isinstance(raw_items, list):
            raise GitHubUserVerificationError(
                f"GitHub response omitted {collection_key}"
            )
        items = [item for item in raw_items if isinstance(item, Mapping)]
        for item in items:
            try:
                item_id = int(item.get("id"))
            except (TypeError, ValueError):
                continue
            if item_id == selected_id:
                return item
        if len(raw_items) < per_page:
            return None
    raise GitHubUserVerificationError(
        f"GitHub {collection_key} listing exceeded the pagination safety limit"
    )


def _get_json(
    endpoint: GitHubApiEndpoint,
    path: str,
    *,
    token: str,
    opener: Callable[..., Any] | None,
    timeout_seconds: float,
) -> dict[str, Any]:
    request = urllib.request.Request(
        endpoint.url(path),
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": token_contract.GITHUB_APP_ACCEPT,
            "X-GitHub-Api-Version": gh_rest_transport.GITHUB_API_VERSION,
            "User-Agent": token_contract.GITHUB_APP_USER_AGENT,
        },
        method="GET",
    )
    try:
        with open_same_origin(
            request,
            endpoint=endpoint,
            timeout_seconds=timeout_seconds,
            opener=opener,
        ) as response:
            raw = response.read()
    except urllib.error.HTTPError as exc:
        raise GitHubUserVerificationError(
            f"GitHub user authorization verification failed with HTTP {exc.code}"
        ) from exc
    except urllib.error.URLError as exc:
        raise GitHubUserVerificationError(
            f"GitHub user authorization verification failed: {exc.reason}"
        ) from exc
    except GitHubApiOriginError as exc:
        raise GitHubUserVerificationError(str(exc)) from exc
    try:
        parsed = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise GitHubUserVerificationError(
            "GitHub user authorization response was not valid JSON"
        ) from exc
    if not isinstance(parsed, dict):
        raise GitHubUserVerificationError(
            "GitHub user authorization response must be a JSON object"
        )
    return parsed


def _positive_id(value: str | int, label: str) -> int:
    if isinstance(value, bool):
        raise GitHubUserVerificationError(f"{label} must be a positive integer")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise GitHubUserVerificationError(
            f"{label} must be a positive integer"
        ) from exc
    if parsed <= 0:
        raise GitHubUserVerificationError(f"{label} must be a positive integer")
    return parsed


def _required_id(value: Any, label: str) -> int:
    return _positive_id(value, label)


def _required_text(value: Any, label: str) -> str:
    cleaned = str(value or "").strip()
    if not cleaned:
        raise GitHubUserVerificationError(f"{label} is missing")
    return cleaned


__all__ = [
    "GitHubUserVerificationError",
    "VerifiedProjectGitHubBinding",
    "verify_project_github_binding",
]
