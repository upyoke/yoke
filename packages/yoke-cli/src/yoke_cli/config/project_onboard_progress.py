"""Progress helpers for project onboarding apply steps."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from yoke_cli.config import onboard_apply_progress
from yoke_cli.config import github_machine
from yoke_cli.config import github_binding_auth
from yoke_cli.config import machine_config
from yoke_cli.config.project_github_adoption import (
    GITHUB_ADOPTION_APP_BINDING,
    ProjectGithubAdoptionError,
    github_sync_mode,
)
from yoke_contracts.project_contract.github_sync_mode import GITHUB_SYNC_ENABLED
from yoke_cli.config.project_onboard_support import dispatch
from yoke_cli.config.project_clone_support import (
    CLONE_OUTCOME_FORK,
    CLONE_OUTCOME_MAKE_IT_MINE,
    ClonePlan,
)


def clone_outcome_action(plan: ClonePlan) -> str | None:
    if plan.outcome == CLONE_OUTCOME_MAKE_IT_MINE and plan.publish is not None:
        return "project-rehome-push"
    if plan.outcome == CLONE_OUTCOME_FORK and plan.fallback_token:
        return "project-fork-remotes"
    return None


def store_github_binding(
    progress: onboard_apply_progress.ProgressCallback | None,
    target: str,
    project: Mapping[str, Any],
    github_adoption: Mapping[str, Any] | None,
    config_path: str | Path | None,
    *,
    persist_sync_mode: bool = False,
) -> Mapping[str, Any] | None:
    choice = str((github_adoption or {}).get("choice") or "")
    sync_mode = github_sync_mode(github_adoption)
    if bool((github_adoption or {}).get("preserve_existing")):
        return {
            "cap_type": "github",
            "mode": choice or "preserve-existing",
            "binding": "preserved",
        }
    # Existing-project onboarding starts from projects.get, so persist the
    # explicit sync choice here too. New projects already received the same
    # value in their create payload; the update is idempotent.
    if persist_sync_mode and choice != GITHUB_ADOPTION_APP_BINDING:
        dispatch(
            "projects.update",
            {
                "project_id": int(project["id"]),
                "slug": str(project["slug"]),
                "name": str(project.get("name") or project["slug"]),
                "github_sync_mode": sync_mode,
            },
            config_path,
        )
    if choice != GITHUB_ADOPTION_APP_BINDING:
        return {
            "cap_type": "github",
            "mode": sync_mode,
            "binding": "skipped",
        }

    github_repo = str(
        (github_adoption or {}).get("github_repo")
        or project.get("github_repo")
        or ""
    ).strip()
    try:
        with github_binding_auth.locked_profile_bound_access_for_binding(
            config_path=config_path,
        ) as authority:
            github_config = machine_config.github_config(config_path)
            repository = _configured_repository(
                github_config,
                github_repo,
                expected_repository_id=_positive_identity(
                    (github_adoption or {}).get("repository_id")
                ),
                expected_installation_id=_positive_identity(
                    (github_adoption or {}).get("installation_id")
                ),
            )
            result = dispatch(
                "projects.github_binding.bind",
                {
                    "project": str(project["id"]),
                    "installation_id": repository["installation_id"],
                    "repository_id": repository["repository_id"],
                    "github_repo": github_repo,
                    "expected_api_url": authority.api_url,
                    "github_user_access_token": authority.token.access_token,
                },
                config_path,
                sensitive_values=(authority.token.access_token,),
            )
    except github_binding_auth.GitHubBindingAuthError as exc:
        raise ProjectGithubAdoptionError(
            "GitHub App authorization could not be refreshed. Run `yoke github "
            "connect`, confirm the App can access this repository, then retry."
        ) from exc
    binding = result.get("binding") if isinstance(result, Mapping) else None
    binding = binding if isinstance(binding, Mapping) else {}
    binding_status = str(binding.get("status") or "pending_permission")
    applied_mode = sync_mode
    if binding_status == "active":
        dispatch(
            "projects.update",
            {
                "project_id": int(project["id"]),
                "slug": str(project["slug"]),
                "name": str(project.get("name") or project["slug"]),
                "github_sync_mode": GITHUB_SYNC_ENABLED,
            },
            config_path,
        )
        applied_mode = GITHUB_SYNC_ENABLED
    permission_status = result.get("permission_status")
    permission_status = (
        dict(permission_status) if isinstance(permission_status, Mapping) else {}
    )
    return {
        "cap_type": "github",
        "mode": applied_mode,
        "binding": binding_status,
        "permission_status": permission_status,
        "result": dict(result),
    }


def _configured_repository(
    config: Mapping[str, Any],
    github_repo: str,
    *,
    expected_repository_id: int | None = None,
    expected_installation_id: int | None = None,
) -> Mapping[str, Any]:
    if not github_repo:
        raise ProjectGithubAdoptionError(
            "GitHub App binding requires a repository in OWNER/REPO form"
        )
    for raw in config.get("repositories") or []:
        if not isinstance(raw, Mapping):
            continue
        if str(raw.get("full_name") or "").casefold() != github_repo.casefold():
            continue
        repository_id = raw.get("repository_id")
        installation_id = raw.get("installation_id")
        if not (
            isinstance(repository_id, int)
            and repository_id > 0
            and isinstance(installation_id, int)
            and installation_id > 0
        ):
            continue
        if (
            expected_repository_id is not None
            and repository_id != expected_repository_id
        ) or (
            expected_installation_id is not None
            and installation_id != expected_installation_id
        ):
            raise ProjectGithubAdoptionError(
                "The selected GitHub repository or App installation identity "
                "changed after it was verified. Check repositories again before "
                "Apply."
            )
        return raw
    raise ProjectGithubAdoptionError(
        f"The connected GitHub App installation does not expose {github_repo}. "
        "Run `yoke github status`, grant the App access to that repository, and retry."
    )


def refresh_github_repository_access(
    config_path: str | Path | None,
    github_repo: str,
    *,
    service_api_url: str | None = None,
) -> Mapping[str, Any]:
    """Refresh App discovery after a create/fork and require the exact repo."""
    try:
        github_machine.status(
            config_path=config_path,
            check=True,
            service_api_url=service_api_url,
        )
    except github_machine.GitHubMachineError as exc:
        raise ProjectGithubAdoptionError(
            f"GitHub finished creating {github_repo}, but Yoke could not refresh "
            "the App installation. The repository and checkout were preserved; "
            "repair the App connection and rerun onboarding to resume."
        ) from exc
    config = machine_config.github_config(config_path)
    try:
        return _configured_repository(config, github_repo)
    except ProjectGithubAdoptionError as exc:
        raise ProjectGithubAdoptionError(
            f"GitHub finished creating {github_repo}, but the live App refresh "
            "does not expose that repository yet. Grant the App access, then "
            "rerun onboarding; the repository and checkout are preserved."
        ) from exc


def record_mutated_repository(
    github_adoption: dict[str, Any],
    github_repo: str,
    config_path: str | Path | None,
    *,
    service_api_url: str | None = None,
) -> None:
    """Update binding intent and refresh App discovery after a repo write."""
    github_adoption["github_repo"] = github_repo
    binding = dict(github_adoption.get("binding") or {})
    binding["repo"] = github_repo
    github_adoption["binding"] = binding
    if github_adoption.get("choice") != GITHUB_ADOPTION_APP_BINDING:
        return None
    repository = refresh_github_repository_access(
        config_path, github_repo, service_api_url=service_api_url,
    )
    expected_repository_id = _positive_identity(
        github_adoption.get("repository_id")
    )
    expected_installation_id = _positive_identity(
        github_adoption.get("installation_id")
    )
    actual_repository_id = _positive_identity(repository.get("repository_id"))
    actual_installation_id = _positive_identity(repository.get("installation_id"))
    if (
        expected_repository_id is not None
        and actual_repository_id != expected_repository_id
    ) or (
        expected_installation_id is not None
        and actual_installation_id != expected_installation_id
    ):
        raise ProjectGithubAdoptionError(
            "The selected GitHub repository or App installation identity changed "
            "during Apply. The checkout was preserved; check repositories again."
        )
    if actual_repository_id is None or actual_installation_id is None:
        raise ProjectGithubAdoptionError(
            "The refreshed GitHub repository identity is incomplete. The checkout "
            "was preserved; check repositories again."
        )
    github_adoption["repository_id"] = actual_repository_id
    github_adoption["installation_id"] = actual_installation_id
    binding.update({
        "repository_id": actual_repository_id,
        "installation_id": actual_installation_id,
    })
    github_adoption["binding"] = binding


def _positive_identity(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else None


def finish_github_binding(
    progress: onboard_apply_progress.ProgressCallback | None,
    target: str,
    github_adoption: Mapping[str, Any] | None,
) -> None:
    binding = (github_adoption or {}).get("binding") or {}
    binding_status = str(binding.get("status") or "")
    status = (
        "done"
        if binding_status == "active"
        else "skipped"
    )
    onboard_apply_progress.emit(progress, "project-github-auth-choice", target, status)


__all__ = [
    "clone_outcome_action",
    "finish_github_binding",
    "record_mutated_repository",
    "refresh_github_repository_access",
    "store_github_binding",
]
