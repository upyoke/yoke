"""Canonical project GitHub App auth + repository resolver.

Local dispatch uses a context-bound App user token. Hosted and self-hosted
control planes mint short-lived installation tokens from global credentials.

Callers name the weakest authority their operation can run under, and the
project's installation is what they inherit by naming nothing. Only an
operation attributed to a person genuinely needs the machine's user
authorization; one the project's installation is itself authorized to perform
should not fail merely because that machine authorization is unreadable.
"""

from __future__ import annotations

from typing import Any, Mapping, Optional

from yoke_contracts.github_auth_transience import (
    GITHUB_AUTH_RETRY_RECIPE,
    GITHUB_AUTH_STATUS_CHECK_RECIPE,
)
from yoke_core.domain.github_app_control_plane import GitHubAppControlPlaneConfig
from yoke_core.domain.github_app_installation_tokens import InstallationTokenCache
from yoke_core.domain.project_github_auth_models import (
    BindingUnavailable,
    GITHUB_AUTHORITY_INSTALLATION,
    GITHUB_AUTHORITY_USER,
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
    UserAuthorizationTransient,
    UserAuthorizationUnavailable,
)
from yoke_core.domain.project_github_auth_state import read_github_state
from yoke_core.domain.project_github_auth_tokens import (
    bind_local_github_user_token_provider,
    bound_local_github_user_token_provider,
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
from yoke_core.domain.project_github_sync_receipt import register_installation_token


def resolve_project_github_auth(
    project: str,
    *,
    db_path: Optional[str] = None,
    conn: Optional[Any] = None,
    token_cache: InstallationTokenCache | None = None,
    token_minter: TokenMinter | None = None,
    control_plane_config: GitHubAppControlPlaneConfig | None = None,
    required_permissions: Mapping[str, str] | None = None,
    required_authority: str = GITHUB_AUTHORITY_INSTALLATION,
    force_refresh: bool = False,
) -> ProjectGithubAuth:
    """Resolve a verified binding and the mode-appropriate bearer token.

    ``required_authority`` is the weakest authority that can perform the
    caller's operation, and it defaults to the weakest one there is. With
    ``GITHUB_AUTHORITY_INSTALLATION`` the project's installation is itself
    authorized, so an unreadable user authorization falls through to an
    installation token instead of refusing work the binding already covers.
    ``GITHUB_AUTHORITY_USER`` means the operation is attributed to a person
    and only the machine's App user authorization will do, so an unreadable
    one is the answer; a caller wanting that says so. Any other value fails
    closed to the strict reading.

    The user-authorization failure outranks the installation one when neither
    path produces a token: on a machine bound to user authority, repairing
    that read is the route back, and a missing service private key is expected
    there.
    """
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
            f"project '{state.project_slug}' GitHub App installation is {installation_status!r}",
        )

    installation_permissions = permissions_dict(state.installation.get("permissions"))
    installation_requirements = installation_contract_permissions(required_permissions)
    token_permissions = scoped_installation_token_permissions(required_permissions)
    permissions_info = permission_status(
        installation_permissions,
        installation_requirements,
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

    local_token, user_authorization_error = _local_user_token(
        state,
        required_authority,
    )
    if local_token is not None:
        return _auth_result(
            state,
            repo,
            local_token,
            installation_permissions,
            token_source=GITHUB_AUTHORITY_USER,
        )
    try:
        credentials = read_app_credentials(state, control_plane_config)
        minted = mint_bound_installation_token(
            state,
            credentials=credentials,
            token_permissions=token_permissions,
            token_cache=token_cache,
            token_minter=token_minter,
            force_refresh=force_refresh,
        )
        token = str(minted.token or "").strip()
        if not token:
            raise TokenMintFailed(
                state.project_slug,
                f"project '{state.project_slug}' GitHub App token resolved empty",
            )
    except ProjectGithubAuthError:
        if user_authorization_error is not None:
            raise user_authorization_error
        raise
    result = _auth_result(state, repo, token, installation_permissions)
    issued_at = getattr(minted, "issued_at", None)
    resolved = ProjectGithubAuth(
        **{
            **result.__dict__,
            "token_issued_at": issued_at.isoformat() if issued_at else "",
            "token_expires_at": minted.expires_at.isoformat(),
        }
    )
    register_installation_token(token, state.project_slug, db_path=db_path)
    return resolved


def _installation_can_perform(required_authority: str) -> bool:
    """Whether the project's installation is itself authorized to do the work.

    Only an operation attributed to a person is beyond it. Any unrecognized
    authority reads as that strict case, so a caller that names nothing
    meaningful is refused rather than quietly re-attributed to the App.
    """
    return required_authority == GITHUB_AUTHORITY_INSTALLATION


def _local_user_token(
    state: ProjectGithubState,
    required_authority: str,
) -> tuple[Optional[str], Optional[ProjectGithubAuthError]]:
    """Read the machine's user token, or say why an installation may stand in.

    Returns ``(None, None)`` when no local provider is bound at all, which is
    the server-side shape: there is no user authorization to fail, and the
    installation path is simply the only one.

    The two read failures are not the same fact and are not flattened here. A
    transient one has already spent its retry budget in
    :func:`_read_user_token_with_retry` and leaves the stored authorization
    standing, so it must never end work the installation can perform; a
    genuine unavailability hands that same work over rather than refusing it.
    Only an operation attributed to a person is refused, and there the two
    part again: the transient verdict is retryable, the unavailable one names
    the read that failed.
    """
    try:
        return resolve_local_user_token(state), None
    except (UserAuthorizationTransient, UserAuthorizationUnavailable) as exc:
        if not _installation_can_perform(required_authority):
            raise
        return None, exc


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
        "--project {project} ...`, or switch the project to disabled"
    ),
    "missing_repo_metadata": "re-bind the GitHub App repo for project {project}",
    "missing_repo_binding": (
        "bind a GitHub App repo with `yoke projects github-binding bind "
        "--project {project} ...`, or keep the project disabled"
    ),
    "missing_installation": "reconnect GitHub, then re-bind project {project}",
    "binding_unavailable": "repair or re-bind GitHub access for project {project}",
    "installation_unavailable": "restore the App installation for project {project}",
    "missing_permission": "approve missing App permissions for project {project}",
    "missing_app_credentials": (
        "configure the control-plane App issuer and private-key file for project {project}"
    ),
    "token_mint_failed": (
        "repair App credentials or installation access for project {project}"
    ),
    "user_authorization_unavailable": (
        f"{GITHUB_AUTH_STATUS_CHECK_RECIPE}, then retry project {{project}}"
    ),
    "user_authorization_transient": (
        "the machine GitHub authorization is busy or temporarily unreachable; "
        f"{GITHUB_AUTH_RETRY_RECIPE} for project {{project}}"
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
    "GITHUB_AUTHORITY_INSTALLATION",
    "GITHUB_AUTHORITY_USER",
    "BindingUnavailable",
    "GITHUB_CAPABILITY_TYPE",
    "InstallationUnavailable",
    "InvalidToken",
    "MissingAppCredentials",
    "MissingCapability",
    "MissingInstallation",
    "MissingPermission",
    "MissingRepoBinding",
    "MissingRepoMetadata",
    "ProjectGithubAuth",
    "ProjectGithubAuthError",
    "TokenMintFailed",
    "TransportFailure",
    "UserAuthorizationTransient",
    "UserAuthorizationUnavailable",
    "bind_local_github_user_token_provider",
    "bound_local_github_user_token_provider",
    "repair_command_hint",
    "resolve_project_github_auth",
]
