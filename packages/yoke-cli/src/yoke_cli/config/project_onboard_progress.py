"""Progress helpers for project onboarding apply steps."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from yoke_cli.config import onboard_apply_progress
from yoke_cli.config import github_machine
from yoke_cli.config import github_user_tokens
from yoke_cli.config import machine_config
from yoke_cli.config.project_github_adoption import (
    GITHUB_ADOPTION_APP_BINDING,
    ProjectGithubAdoptionError,
    github_sync_mode,
)
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
    github_config = machine_config.github_config(config_path)
    repository = _configured_repository(github_config, github_repo)
    expected_api_url = str(github_config.get("api_url") or "").strip()
    if not expected_api_url:
        raise ProjectGithubAdoptionError(
            "The connected GitHub App configuration has no API URL. Run "
            "`yoke github connect` again before binding this repository."
        )
    try:
        access_token = github_user_tokens.access_token_from_machine_config(
            config_path=config_path,
        ).access_token
    except github_user_tokens.GitHubUserTokenError as exc:
        raise ProjectGithubAdoptionError(
            "GitHub App authorization could not be refreshed. Run `yoke github "
            "connect`, confirm the App can access this repository, then retry."
        ) from exc
    result = dispatch(
        "projects.github_binding.bind",
        {
            "project": str(project["id"]),
            "installation_id": repository["installation_id"],
            "repository_id": repository["repository_id"],
            "github_repo": github_repo,
            "expected_api_url": expected_api_url,
            "github_user_access_token": access_token,
        },
        config_path,
    )
    binding = result.get("binding") if isinstance(result, Mapping) else None
    binding = binding if isinstance(binding, Mapping) else {}
    binding_status = str(binding.get("status") or "pending_permission")
    permission_status = result.get("permission_status")
    permission_status = (
        dict(permission_status) if isinstance(permission_status, Mapping) else {}
    )
    return {
        "cap_type": "github",
        "mode": str(result.get("github_sync_mode") or sync_mode),
        "binding": binding_status,
        "permission_status": permission_status,
        "result": dict(result),
    }


def _configured_repository(
    config: Mapping[str, Any],
    github_repo: str,
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
        if isinstance(repository_id, int) and isinstance(installation_id, int):
            return raw
    raise ProjectGithubAdoptionError(
        f"The connected GitHub App installation does not expose {github_repo}. "
        "Run `yoke github status`, grant the App access to that repository, and retry."
    )


def refresh_github_repository_access(
    config_path: str | Path | None,
    github_repo: str,
) -> Mapping[str, Any]:
    """Refresh App discovery after a create/fork and require the exact repo."""
    try:
        github_machine.status(config_path=config_path, check=True)
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
) -> None:
    """Update binding intent and refresh App discovery after a repo write."""
    github_adoption["github_repo"] = github_repo
    binding = dict(github_adoption.get("binding") or {})
    binding["repo"] = github_repo
    github_adoption["binding"] = binding
    if github_adoption.get("choice") != GITHUB_ADOPTION_APP_BINDING:
        return None
    refresh_github_repository_access(config_path, github_repo)


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
