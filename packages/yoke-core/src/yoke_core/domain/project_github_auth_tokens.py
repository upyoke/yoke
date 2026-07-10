"""Local-user and hosted-installation token resolution for project auth."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Callable, Iterator, Mapping

from yoke_contracts.github_origin import (
    GitHubApiEndpoint,
    GitHubApiOriginError,
    validate_github_api_endpoint,
)
from yoke_contracts.github_app_installation_permissions import (
    GITHUB_METADATA_READ_PERMISSION_LEVELS,
    REQUIRED_GITHUB_APP_REPOSITORY_PERMISSION_LEVELS,
)
from yoke_core.domain.github_app_control_plane import (
    GitHubAppControlPlaneConfig,
    GitHubAppControlPlaneConfigError,
    load_github_app_control_plane_config,
)
from yoke_core.domain.github_app_dispatch_context import (
    LOCAL_API_ENDPOINT,
    LOCAL_USER_TOKEN_PROVIDER,
)
from yoke_core.domain.github_app_installation_tokens import InstallationTokenCache
from yoke_core.domain.github_app_token_models import (
    GitHubAppTokenError,
    InstallationToken,
)
from yoke_core.domain.project_github_auth_models import (
    AppCredentials,
    MissingAppCredentials,
    MissingRepoMetadata,
    ProjectGithubState,
    TokenMintFailed,
    TokenMinter,
    UserAuthorizationUnavailable,
)

_INSTALLATION_TOKEN_CACHE = InstallationTokenCache()


@contextmanager
def bind_local_github_user_token_provider(
    provider: Callable[[], str],
    *,
    api_url: str | GitHubApiEndpoint | None = None,
) -> Iterator[None]:
    if not callable(provider):
        raise TypeError("GitHub user token provider must be callable")
    endpoint = (
        api_url
        if isinstance(api_url, GitHubApiEndpoint)
        else validate_github_api_endpoint(api_url)
    )
    reset_token = LOCAL_USER_TOKEN_PROVIDER.set(provider)
    reset_endpoint = LOCAL_API_ENDPOINT.set(endpoint)
    try:
        yield
    finally:
        LOCAL_API_ENDPOINT.reset(reset_endpoint)
        LOCAL_USER_TOKEN_PROVIDER.reset(reset_token)


def resolve_local_user_token(state: ProjectGithubState) -> str | None:
    provider = LOCAL_USER_TOKEN_PROVIDER.get()
    if provider is None:
        return None
    endpoint = LOCAL_API_ENDPOINT.get()
    try:
        bound_api_url = _bound_api_url(state)
    except ValueError as exc:
        raise UserAuthorizationUnavailable(
            state.project_slug,
            "the project GitHub API origin is unavailable; re-bind the repository",
        ) from exc
    if endpoint is None or endpoint.base_url != bound_api_url:
        raise UserAuthorizationUnavailable(
            state.project_slug,
            "local GitHub authorization does not match the bound repository's "
            "GitHub API origin; reconnect using the matching GitHub deployment",
        )
    try:
        token = str(provider() or "").strip()
    except Exception as exc:
        raise UserAuthorizationUnavailable(
            state.project_slug,
            "local GitHub App user authorization is unavailable; reconnect "
            "GitHub on this machine",
        ) from exc
    if not token:
        raise UserAuthorizationUnavailable(
            state.project_slug,
            "local GitHub App user authorization returned an empty access token",
        )
    return token


def read_app_credentials(
    state: ProjectGithubState,
    config: GitHubAppControlPlaneConfig | None,
) -> AppCredentials:
    try:
        selected = config or load_github_app_control_plane_config()
    except GitHubAppControlPlaneConfigError as exc:
        raise MissingAppCredentials(
            state.project_slug,
            "GitHub App control-plane credentials are unavailable; check the "
            "service issuer and private-key mount",
        ) from exc
    try:
        bound_api_url = _bound_api_url(state)
    except ValueError as exc:
        raise MissingAppCredentials(
            state.project_slug,
            "the project GitHub API origin is unavailable; re-bind the repository",
        ) from exc
    if selected.endpoint.base_url != bound_api_url:
        raise MissingAppCredentials(
            state.project_slug,
            "GitHub App control-plane credentials do not match the bound "
            "repository's GitHub API origin",
        )
    return AppCredentials(
        issuer=selected.issuer,
        private_key_pem=selected.private_key_pem,
        api_url=selected.endpoint.base_url,
        private_key_file=selected.private_key_file,
    )


def mint_bound_installation_token(
    state: ProjectGithubState,
    *,
    credentials: AppCredentials,
    token_permissions: Mapping[str, str],
    token_cache: InstallationTokenCache | None,
    token_minter: TokenMinter | None,
) -> InstallationToken:
    repository_id = _required_repository_id(
        state.binding.get("repository_id") if state.binding else None,
        project=state.project_slug,
    )
    kwargs: dict[str, Any] = {
        "issuer": credentials.issuer,
        "private_key_pem": credentials.private_key_pem,
        "installation_id": str(state.binding.get("installation_id") or ""),
        "api_url": credentials.api_url,
        "permissions": dict(token_permissions),
    }
    kwargs["repository_ids"] = [repository_id]
    try:
        if token_minter is not None:
            return token_minter(**kwargs)
        return (token_cache or _INSTALLATION_TOKEN_CACHE).get_or_mint(**kwargs)
    except GitHubAppTokenError as exc:
        raise TokenMintFailed(
            state.project_slug,
            f"project '{state.project_slug}' GitHub App token mint failed: {exc}",
        ) from exc


def installation_contract_permissions(
    additional: Mapping[str, str] | None,
) -> dict[str, str]:
    """Return the full App grant required for baseline plus one operation."""
    return _permissions_with_minimum(
        REQUIRED_GITHUB_APP_REPOSITORY_PERMISSION_LEVELS,
        additional,
    )


def scoped_installation_token_permissions(
    operation: Mapping[str, str] | None,
) -> dict[str, str]:
    """Return the least-privilege token scope for one repository operation."""
    return _permissions_with_minimum(
        GITHUB_METADATA_READ_PERMISSION_LEVELS,
        operation,
    )


def _permissions_with_minimum(
    minimum: Mapping[str, str],
    additional: Mapping[str, str] | None,
) -> dict[str, str]:
    merged = dict(minimum)
    levels = {"none": 0, "read": 1, "write": 2}
    for key, value in (additional or {}).items():
        permission = str(key or "").strip()
        access = str(value or "").strip().lower()
        if not permission or access not in {"read", "write"}:
            raise ValueError("required GitHub permissions must use valid access levels")
        current = str(merged.get(permission) or "none").lower()
        if levels[access] > levels.get(current, 0):
            merged[permission] = access
    return merged


def _required_repository_id(value: Any, *, project: str) -> int:
    if isinstance(value, bool):
        raise MissingRepoMetadata(
            project, f"project '{project}' bound GitHub repository id is invalid",
        )
    try:
        parsed = int(str(value or "").strip())
    except ValueError as exc:
        raise MissingRepoMetadata(
            project, f"project '{project}' bound GitHub repository id is invalid",
        ) from exc
    if parsed <= 0:
        raise MissingRepoMetadata(
            project, f"project '{project}' bound GitHub repository id is invalid",
        )
    return parsed


def _bound_api_url(state: ProjectGithubState) -> str:
    binding_url = str(
        state.binding.get("api_url") if state.binding else ""
    ).strip()
    installation_url = str(
        state.installation.get("api_url") if state.installation else ""
    ).strip()
    if not binding_url or not installation_url:
        raise ValueError("bound GitHub API URL is missing")
    try:
        binding_endpoint = validate_github_api_endpoint(binding_url)
        installation_endpoint = validate_github_api_endpoint(installation_url)
    except GitHubApiOriginError as exc:
        raise ValueError("bound GitHub API URL is invalid") from exc
    if binding_endpoint.base_url != installation_endpoint.base_url:
        raise ValueError("bound GitHub API URLs do not match")
    return binding_endpoint.base_url


__all__ = [
    "bind_local_github_user_token_provider",
    "installation_contract_permissions",
    "mint_bound_installation_token",
    "read_app_credentials",
    "resolve_local_user_token",
    "scoped_installation_token_permissions",
]
