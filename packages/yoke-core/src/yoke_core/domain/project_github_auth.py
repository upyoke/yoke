"""Canonical project GitHub App auth + repository resolver.

Local dispatch uses a context-bound App user token. Hosted and self-hosted
control planes mint short-lived installation tokens from global credentials.
"""

from __future__ import annotations

from typing import Any, Mapping, Optional

from yoke_core.domain.github_app_control_plane import GitHubAppControlPlaneConfig
from yoke_core.domain.github_app_installation_tokens import InstallationTokenCache
from yoke_core.domain.project_github_auth_models import (
    BindingUnavailable,
    GITHUB_CAPABILITY_TYPE,
    InstallationUnavailable,
    InvalidToken,
    MissingAppCredentials,
    MissingCapability,
    MissingInstallation,
    MissingPermission,
    MissingRepoBinding,
    MissingRepoMetadata,
    ProjectGithubAuth,
    ProjectGithubAuthError,
    ProjectGithubState,
    TokenMintFailed,
    TokenMinter,
    TransportFailure,
    UserAuthorizationUnavailable,
)
from yoke_core.domain.project_github_auth_state import read_github_state
from yoke_core.domain.project_github_auth_tokens import (
    bind_local_github_user_token_provider,
    installation_contract_permissions,
    mint_bound_installation_token,
    read_app_credentials,
    resolve_local_user_token,
    scoped_installation_token_permissions,
)
from yoke_core.domain.project_github_binding import (
    BINDING_ACTIVE,
    INSTALLATION_ACTIVE,
)
from yoke_core.domain.project_github_binding_payload import (
    permission_status,
    permissions_dict,
)


def resolve_project_github_auth(
    project: str,
    *,
    db_path: Optional[str] = None,
    conn: Optional[Any] = None,
    token_cache: InstallationTokenCache | None = None,
    token_minter: TokenMinter | None = None,
    control_plane_config: GitHubAppControlPlaneConfig | None = None,
    required_permissions: Mapping[str, str] | None = None,
) -> ProjectGithubAuth:
    """Resolve a verified binding and the mode-appropriate bearer token."""
    state = read_github_state(project, db_path, conn=conn)
    if not state.has_capability:
        raise MissingCapability(
            state.project_slug,
            f"project '{state.project_slug}' has no GitHub App capability row; "
            "bind a repository with `yoke projects github-binding bind`",
        )
    if state.binding is None:
        raise MissingRepoBinding(
            state.project_slug,
            f"project '{state.project_slug}' is not bound to a GitHub App repository",
        )
    repo = str(state.binding.get("github_repo") or "").strip()
    if not repo:
        raise MissingRepoMetadata(
            state.project_slug,
            f"project '{state.project_slug}' has no bound GitHub repository",
        )
    if state.installation is None:
        raise MissingInstallation(
            state.project_slug,
            f"project '{state.project_slug}' GitHub App installation is missing",
        )
    installation_status = str(state.installation.get("status") or "")
    if installation_status != INSTALLATION_ACTIVE:
        raise InstallationUnavailable(
            state.project_slug,
            f"project '{state.project_slug}' GitHub App installation is "
            f"{installation_status!r}",
        )

    installation_permissions = permissions_dict(state.installation.get("permissions"))
    installation_requirements = installation_contract_permissions(
        required_permissions
    )
    token_permissions = scoped_installation_token_permissions(required_permissions)
    permissions_info = permission_status(
        installation_permissions, installation_requirements,
    )
    if permissions_info.get("status") != "satisfied":
        missing = ", ".join(permissions_info.get("missing") or [])
        raise MissingPermission(
            state.project_slug,
            f"project '{state.project_slug}' GitHub App binding is missing "
            f"permissions: {missing or 'permission metadata is unverified'}",
        )
    binding_status = str(state.binding.get("status") or "")
    if binding_status != BINDING_ACTIVE:
        raise BindingUnavailable(
            state.project_slug,
            f"project '{state.project_slug}' GitHub binding is {binding_status!r}",
        )

    local_token = resolve_local_user_token(state)
    if local_token is not None:
        return _auth_result(
            state, repo, local_token, installation_permissions,
            token_source="github_app_user",
        )
    credentials = read_app_credentials(state, control_plane_config)
    minted = mint_bound_installation_token(
        state,
        credentials=credentials,
        token_permissions=token_permissions,
        token_cache=token_cache,
        token_minter=token_minter,
    )
    token = str(minted.token or "").strip()
    if not token:
        raise TokenMintFailed(
            state.project_slug,
            f"project '{state.project_slug}' GitHub App token resolved empty",
        )
    result = _auth_result(state, repo, token, installation_permissions)
    return ProjectGithubAuth(
        **{
            **result.__dict__,
            "token_expires_at": minted.expires_at.isoformat(),
        }
    )


def _auth_result(
    state: ProjectGithubState,
    repo: str,
    token: str,
    permissions: Mapping[str, Any],
    *,
    token_source: str = "github_app_installation",
) -> ProjectGithubAuth:
    return ProjectGithubAuth(
        project=state.project_slug,
        repo=repo,
        token=token,
        installation_id=str(state.binding.get("installation_id") or ""),
        token_source=token_source,
        permissions=dict(permissions),
    )


_HINT_BY_CODE: Mapping[str, str] = {
    "missing_capability": (
        "bind a GitHub App repo with `yoke projects github-binding bind "
        "--project {project} ...`, or switch the project to backlog-only"
    ),
    "missing_repo_metadata": "re-bind the GitHub App repo for project {project}",
    "missing_repo_binding": (
        "bind a GitHub App repo with `yoke projects github-binding bind "
        "--project {project} ...`, or keep the project backlog-only"
    ),
    "missing_installation": "reconnect GitHub, then re-bind project {project}",
    "binding_unavailable": "repair or re-bind GitHub access for project {project}",
    "installation_unavailable": "restore the App installation for project {project}",
    "missing_permission": "approve missing App permissions for project {project}",
    "missing_app_credentials": (
        "configure the control-plane App issuer and private-key file for "
        "project {project}"
    ),
    "token_mint_failed": (
        "repair App credentials or installation access for project {project}"
    ),
    "user_authorization_unavailable": (
        "reconnect GitHub on this machine, then retry project {project}"
    ),
    "invalid_token": "reconnect GitHub App access for project {project}",
    "transport_failure": "retry once network access is restored for project {project}",
}


def repair_command_hint(error: ProjectGithubAuthError, project: str) -> str:
    template = _HINT_BY_CODE.get(error.code)
    if template is None:
        return f"check the GitHub App binding and credentials for project {project}"
    return template.format(project=project)


__all__ = [
    "BindingUnavailable", "GITHUB_CAPABILITY_TYPE", "InstallationUnavailable",
    "InvalidToken", "MissingAppCredentials", "MissingCapability",
    "MissingInstallation", "MissingPermission", "MissingRepoBinding",
    "MissingRepoMetadata", "ProjectGithubAuth", "ProjectGithubAuthError",
    "TokenMintFailed", "TransportFailure", "UserAuthorizationUnavailable",
    "bind_local_github_user_token_provider", "repair_command_hint",
    "resolve_project_github_auth",
]
