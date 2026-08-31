"""Private GitHub remote creation and project binding for git bootstrap."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from yoke_cli.config import machine_config
from yoke_cli.config import onboard_project_github_inputs
from yoke_cli.config import project_clone_resume
from yoke_cli.config import project_onboard_progress
from yoke_cli.config.github_repository_name import (
    GitHubRepositoryNameError,
    validated as validated_repo_name,
)
from yoke_cli.config.project_github_adoption import GITHUB_ADOPTION_APP_BINDING
from yoke_cli.config.project_onboard_support import (
    ProjectDispatchError,
    ProjectOnboardError,
    dispatch,
)
from yoke_cli.config.project_publish_request import PublishRequest
from yoke_contracts import github_origin


def publish_request(
    root: Path,
    *,
    owner: str | None,
    name: str | None,
    config_path: str | Path | None,
) -> PublishRequest:
    """Hydrate a private create-repo request from machine GitHub auth."""

    try:
        github = machine_config.github_config(config_path)
    except machine_config.MachineConfigError as exc:
        raise ProjectOnboardError(
            f"{exc}. Run `yoke github connect`, then retry "
            f"`yoke project git bootstrap {root} --yes`."
        ) from exc
    if not github:
        raise ProjectOnboardError(
            "machine GitHub App authorization is not configured. "
            "Run `yoke github connect`, then retry "
            f"`yoke project git bootstrap {root} --yes`."
        )
    resolved_owner = (owner or default_owner(github)).strip()
    if not resolved_owner:
        raise ProjectOnboardError(
            "pass --owner LOGIN (or connect GitHub so the authorized login "
            f"is known), then retry `yoke project git bootstrap {root} --yes`."
        )
    try:
        resolved_name = validated_repo_name(name or root.name)
    except GitHubRepositoryNameError as exc:
        raise ProjectOnboardError(
            f"{exc} Pass --name NAME, then retry "
            f"`yoke project git bootstrap {root} --yes`."
        ) from exc
    login = default_owner(github) or resolved_owner
    request = PublishRequest(
        owner=resolved_owner,
        name=resolved_name,
        user_login=login,
        token=None,
        private=True,
        use_machine_github=True,
        create_repository=True,
    )
    cfg = (
        Path(config_path) if config_path is not None
        else machine_config.config_path(None)
    )
    try:
        hydrated = onboard_project_github_inputs.hydrate_machine_github_inputs(
            {"publish": request},
            cfg,
        )
    except onboard_project_github_inputs.MachineGitHubInputError as exc:
        raise ProjectOnboardError(
            f"{exc} Run `yoke github connect`, then retry "
            f"`yoke project git bootstrap {root} --yes`."
        ) from exc
    publish = hydrated.get("publish")
    if not isinstance(publish, PublishRequest):
        raise ProjectOnboardError(
            "GitHub App user authorization is required to create a private "
            f"repository. Run `yoke github connect`, then retry "
            f"`yoke project git bootstrap {root} --yes`."
        )
    return publish


def default_owner(github: Mapping[str, Any]) -> str:
    auth = github.get("authorization")
    if isinstance(auth, Mapping):
        login = str(auth.get("login") or "").strip()
        if login:
            return login
    for row in github.get("installations") or []:
        if not isinstance(row, Mapping):
            continue
        account = str(row.get("account_login") or "").strip()
        if account:
            return account
    return ""


def origin_full_name(root: Path) -> str | None:
    url = project_clone_resume.remote_url(root, "origin")
    if not url:
        return None
    try:
        return github_origin.normalize_github_repository(url)
    except github_origin.GitHubApiOriginError:
        return None


def bind_project(
    project_slug: str,
    github_repo: str,
    config_path: str | Path | None,
) -> bool:
    """Refresh App discovery and record the project's GitHub binding."""

    try:
        fetched = dispatch(
            "projects.get", {"project": project_slug}, config_path,
        )
    except ProjectDispatchError as exc:
        raise ProjectOnboardError(
            f"could not load project {project_slug} to record the GitHub "
            f"binding: {exc}. Create the project first, then retry "
            f"`yoke project git bootstrap CHECKOUT --project {project_slug} --yes`."
        ) from exc
    project = fetched.get("project") if isinstance(fetched, Mapping) else None
    if not isinstance(project, Mapping):
        raise ProjectOnboardError(
            f"project {project_slug} did not return a project row; cannot bind "
            f"{github_repo}."
        )
    adoption = {
        "choice": GITHUB_ADOPTION_APP_BINDING,
        "github_repo": github_repo,
    }
    project_onboard_progress.record_mutated_repository(
        adoption, github_repo, config_path,
    )
    project_onboard_progress.store_github_binding(
        None, "skip", project, adoption, config_path,
    )
    return True


__all__ = [
    "bind_project",
    "default_owner",
    "origin_full_name",
    "publish_request",
]
