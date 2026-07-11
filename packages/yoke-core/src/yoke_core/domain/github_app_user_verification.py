"""Verify project binding intent with a transient GitHub App user token."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping
from yoke_contracts.github_origin import (
    DEFAULT_GITHUB_API_URL,
    GitHubApiEndpoint,
    GitHubApiOriginError,
    validate_github_api_endpoint,
)
from yoke_core.domain.github_app_control_plane import GitHubAppControlPlaneConfig
from yoke_core.domain.github_app_binding_verification_budget import (
    GitHubBindingVerificationBudget,
    GitHubBindingVerificationBudgetError,
)
from yoke_core.domain.github_app_server_installation import (
    GitHubServerInstallationVerificationError,
    ServerInstallationFetcher,
    resolve_binding_verification_authority,
    verify_user_installation_against_server,
)
from yoke_core.domain.github_app_user_verification_transport import (
    GitHubUserVerificationError,
    _find_paginated,
    _get_json,
)
from yoke_core.domain.project_github_binding_payload import normalize_github_repo


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
    control_plane_config: GitHubAppControlPlaneConfig | None = None,
    server_installation_opener: Callable[..., Any] | None = None,
    server_installation_fetcher: ServerInstallationFetcher | None = None,
    timeout_seconds: float = 30.0,
    verification_budget: GitHubBindingVerificationBudget | None = None,
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
        budget = verification_budget or GitHubBindingVerificationBudget.for_operation(
            timeout_seconds
        )
    except GitHubBindingVerificationBudgetError as exc:
        raise GitHubUserVerificationError(str(exc)) from exc
    try:
        selected_endpoint, server_config = resolve_binding_verification_authority(
            endpoint=endpoint,
            config=control_plane_config,
        )
    except GitHubServerInstallationVerificationError as exc:
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
        budget=budget,
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
        budget=budget,
    )
    if installation is None:
        raise GitHubUserVerificationError(
            "the signed-in GitHub user cannot access the requested App installation"
        )
    installation_status = "suspended" if installation.get("suspended_at") else "active"
    account = installation.get("account")
    if not isinstance(account, Mapping):
        raise GitHubUserVerificationError(
            "GitHub installation account metadata is missing"
        )
    account_id = _required_id(account.get("id"), "installation account id")
    account_login = _required_text(account.get("login"), "installation account login")
    account_type = _required_text(account.get("type"), "installation account type")
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
    repository_selection = str(installation.get("repository_selection") or "").strip()
    if repository_selection not in {"all", "selected"}:
        raise GitHubUserVerificationError(
            "GitHub installation repository_selection is invalid"
        )
    if server_config is not None:
        try:
            verify_user_installation_against_server(
                config=server_config,
                installation_id=selected_installation_id,
                account_id=account_id,
                account_login=account_login,
                account_type=account_type,
                repository_selection=repository_selection,
                permissions=permissions,
                status=installation_status,
                opener=server_installation_opener,
                fetcher=server_installation_fetcher,
                timeout_seconds=timeout_seconds,
                budget=budget,
            )
        except GitHubServerInstallationVerificationError as exc:
            raise GitHubUserVerificationError(str(exc)) from exc

    repository = _find_paginated(
        selected_endpoint,
        f"/user/installations/{selected_installation_id}/repositories",
        collection_key="repositories",
        selected_id=selected_repository_id,
        token=access_token,
        opener=opener,
        timeout_seconds=timeout_seconds,
        budget=budget,
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

    try:
        budget.checkpoint()
    except GitHubBindingVerificationBudgetError as exc:
        raise GitHubUserVerificationError(str(exc)) from exc
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
            repository.get("default_branch"),
            "repository default branch",
        ),
        installation_status=installation_status,
        api_url=selected_endpoint.base_url,
    )


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
