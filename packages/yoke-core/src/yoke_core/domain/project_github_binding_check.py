"""Re-verify one project's GitHub App binding against GitHub on request.

Hosted universes stay current from signed GitHub webhooks. Local and
self-hosted universes have no webhook delivery, so their binding facts are
as fresh as the last check; this is that check.

Two authorities can answer, chosen by what the calling process holds:

* a machine-local GitHub App user authorization (an in-process dispatch on
  the operator's machine binds one), which re-runs the same verification
  ``projects.github_binding.bind`` performs, with the binding's own ids;
* the server's own GitHub App key (a self-hosted server with GitHub
  automation configured), which reads the installation with the App JWT
  and the repository with an installation token, then applies the result
  the way a lifecycle delivery would.
"""

from __future__ import annotations

from typing import Any, Callable, Optional

from yoke_core.domain.github_app_binding_verification_budget import (
    GitHubBindingVerificationBudget,
)
from yoke_core.domain.github_app_control_plane import (
    GitHubAppControlPlaneConfig,
    GitHubAppControlPlaneConfigError,
    load_github_app_control_plane_config,
)
from yoke_core.domain.github_app_installation_tokens import InstallationTokenCache
from yoke_core.domain.github_app_server_installation import (
    ServerVerifiedInstallation,
    fetch_server_app_installation,
)
from yoke_core.domain.github_app_user_verification_transport import (
    _find_paginated,
)
from yoke_core.domain.project_github_auth_state import read_github_state
from yoke_core.domain.project_github_auth_tokens import (
    bound_local_github_user_token_provider,
    resolve_local_user_token,
)

CHECK_TIMEOUT_SECONDS = 30.0
_REPOSITORY_READ_PERMISSIONS = {"metadata": "read"}

CHECK_RECIPE = (
    "Run the check where GitHub authority lives: for a local universe, "
    "`yoke projects github-binding check --project {project}` on the "
    "operator's machine after `yoke github connect`; for a self-hosted "
    "server, configure its GitHub App key (docs/public/self-hosting/install.md, GitHub App "
    "server automation) and check again"
)


class ProjectGithubBindingCheckError(ValueError):
    """The binding could not be checked; ``code`` and ``recovery`` name why."""

    def __init__(self, code: str, message: str, recovery: str) -> None:
        super().__init__(message)
        self.code = code
        self.recovery = recovery


ServerFetcher = Callable[..., ServerVerifiedInstallation]
RepositoryFinder = Callable[..., Any]


def cmd_check_project_github_binding(
    project: str,
    *,
    db_path: Optional[str] = None,
    conn: Optional[Any] = None,
    control_plane_config: GitHubAppControlPlaneConfig | None = None,
    user_verifier: Callable[..., Any] | None = None,
    server_fetcher: ServerFetcher | None = None,
    repository_finder: RepositoryFinder | None = None,
    token_cache: InstallationTokenCache | None = None,
) -> dict[str, Any]:
    """Refresh the binding's installation and repository facts from GitHub."""
    state = read_github_state(project, db_path, conn=conn)
    binding = state.binding
    if binding is None:
        raise ProjectGithubBindingCheckError(
            "github_binding_missing",
            f"project '{state.project_slug}' has no GitHub App repository "
            "binding to check",
            "Bind a repository with `yoke projects github-binding bind`, "
            "then check again",
        )
    installation_id = str(binding.get("installation_id") or "")
    repository_id = str(binding.get("repository_id") or "")
    github_repo = str(binding.get("github_repo") or "")
    api_url = str(binding.get("api_url") or "")
    if bound_local_github_user_token_provider() is not None:
        from yoke_core.domain.project_github_binding import cmd_bind_project_repo

        return cmd_bind_project_repo(
            project,
            installation_id=installation_id,
            repository_id=repository_id,
            github_repo=github_repo,
            expected_api_url=api_url,
            github_user_access_token=resolve_local_user_token(state) or "",
            db_path=db_path,
            conn=conn,
            verifier=user_verifier,
        )
    config = control_plane_config or _server_app_config(state.project_slug)
    if config.endpoint.base_url != api_url:
        raise ProjectGithubBindingCheckError(
            "github_check_origin_mismatch",
            "this server's GitHub App answers for "
            f"{config.endpoint.base_url}, but project '{state.project_slug}' "
            f"is bound through {api_url}",
            "Re-bind the repository through this server's GitHub deployment "
            "with `yoke projects github-binding bind`, then check again",
        )
    budget = GitHubBindingVerificationBudget.for_operation(CHECK_TIMEOUT_SECONDS)
    installation = (server_fetcher or fetch_server_app_installation)(
        config=config,
        installation_id=installation_id,
        timeout_seconds=CHECK_TIMEOUT_SECONDS,
        budget=budget,
    )
    repository_available = installation.status == "active" and _repository_visible(
        config,
        installation_id=installation_id,
        repository_id=repository_id,
        budget=budget,
        finder=repository_finder or _find_paginated,
        token_cache=token_cache or InstallationTokenCache(),
    )
    from yoke_core.domain.project_github_binding_lifecycle import (
        cmd_apply_project_github_binding_lifecycle,
    )

    return cmd_apply_project_github_binding_lifecycle(
        project,
        installation_id=installation_id,
        repository_id=repository_id,
        installation_status=installation.status,
        repository_available=repository_available,
        permissions=dict(installation.permissions),
        operator_check=True,
        db_path=db_path,
        conn=conn,
    )


def _server_app_config(project_slug: str) -> GitHubAppControlPlaneConfig:
    try:
        return load_github_app_control_plane_config()
    except GitHubAppControlPlaneConfigError as exc:
        raise ProjectGithubBindingCheckError(
            "github_check_authority_unavailable",
            "this process holds neither a machine GitHub App user "
            "authorization nor the server's GitHub App key, so it cannot ask "
            "GitHub about the binding",
            CHECK_RECIPE.format(project=project_slug),
        ) from exc


def _repository_visible(
    config: GitHubAppControlPlaneConfig,
    *,
    installation_id: str,
    repository_id: str,
    budget: GitHubBindingVerificationBudget,
    finder: RepositoryFinder,
    token_cache: InstallationTokenCache,
) -> bool:
    token = token_cache.get_or_mint(
        issuer=config.issuer,
        private_key_pem=config.private_key_pem,
        installation_id=int(installation_id),
        api_url=config.endpoint.base_url,
        permissions=_REPOSITORY_READ_PERMISSIONS,
    )
    found = finder(
        config.endpoint,
        "/installation/repositories",
        collection_key="repositories",
        selected_id=int(repository_id),
        token=token.token,
        opener=None,
        timeout_seconds=CHECK_TIMEOUT_SECONDS,
        budget=budget,
    )
    return found is not None


__all__ = [
    "CHECK_RECIPE",
    "ProjectGithubBindingCheckError",
    "cmd_check_project_github_binding",
]
