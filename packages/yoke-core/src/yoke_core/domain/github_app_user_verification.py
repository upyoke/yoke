"""Verify project binding intent with a transient GitHub App user token."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping
from yoke_contracts.github_binding_metadata import (
    GitHubBindingMetadataError,
    validate_account_login,
    validate_account_type,
    validate_binding_metadata,
    validate_permissions,
    validate_repository_full_name,
    validate_repository_selection,
)
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
    try:
        expected_repo = validate_repository_full_name(expected_github_repo)
    except GitHubBindingMetadataError as exc:
        raise GitHubUserVerificationError(
            "github_repo must be the expected GitHub owner/repo"
        ) from exc
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
    try:
        validate_account_login(user.get("login"))
    except GitHubBindingMetadataError as exc:
        raise GitHubUserVerificationError(str(exc)) from exc

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
    try:
        account_login = validate_account_login(account.get("login"))
        account_type = validate_account_type(account.get("type"))
    except GitHubBindingMetadataError as exc:
        raise GitHubUserVerificationError(str(exc)) from exc
    raw_permissions = installation.get("permissions")
    permissions = raw_permissions if isinstance(raw_permissions, Mapping) else {}
    if not permissions:
        raise GitHubUserVerificationError(
            "GitHub installation permission metadata is missing"
        )
    try:
        permissions = validate_permissions(permissions)
        repository_selection = validate_repository_selection(
            installation.get("repository_selection")
        )
    except GitHubBindingMetadataError as exc:
        raise GitHubUserVerificationError(str(exc)) from exc
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
    canonical_repo = repository.get("full_name")
    try:
        normalized_canonical_repo = validate_repository_full_name(canonical_repo)
    except GitHubBindingMetadataError as exc:
        raise GitHubUserVerificationError(
            "GitHub repository full_name is invalid"
        ) from exc
    if normalized_canonical_repo.casefold() != expected_repo.casefold():
        raise GitHubUserVerificationError(
            f"the selected repository id is not {expected_repo}"
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
    try:
        metadata = validate_binding_metadata(
            installation_id=selected_installation_id,
            account_id=account_id,
            account_login=account_login,
            account_type=account_type,
            repository_selection=repository_selection,
            permissions=permissions,
            repository_id=selected_repository_id,
            github_repo=normalized_canonical_repo,
            default_branch=repository.get("default_branch"),
            installation_status=installation_status,
        )
    except GitHubBindingMetadataError as exc:
        raise GitHubUserVerificationError(str(exc)) from exc
    return VerifiedProjectGitHubBinding(
        installation_id=metadata.installation_id,
        account_id=metadata.account_id,
        account_login=metadata.account_login,
        account_type=metadata.account_type,
        repository_selection=metadata.repository_selection,
        permissions=metadata.permissions,
        repository_id=metadata.repository_id,
        github_repo=metadata.github_repo,
        default_branch=metadata.default_branch,
        installation_status=metadata.installation_status,
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


__all__ = [
    "GitHubUserVerificationError",
    "VerifiedProjectGitHubBinding",
    "verify_project_github_binding",
]
