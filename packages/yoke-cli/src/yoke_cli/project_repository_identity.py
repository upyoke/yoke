"""Client-side checkout identity guard for project repository writes."""

from __future__ import annotations

from pathlib import Path

from yoke_cli.config import github_repo_config
from yoke_contracts.github_origin import (
    GitHubApiOriginError,
    github_web_url_from_api,
    normalize_github_repository,
)
from yoke_contracts.refusal_recovery import compose_refusal


class ProjectRepositoryIdentityError(RuntimeError):
    """The checkout cannot be safely written under the selected project."""


def assert_project_repository(
    root: Path,
    project: str | int | None,
    *,
    config_path: str | Path | None = None,
    explicit_env: str | None = None,
    session_id: str | None = None,
    timeout_s: float | None = None,
) -> None:
    """Refuse an existing origin that differs from the project's binding.

    Missing origins remain valid for local setup. Read binding status without
    GitHub network calls; no snapshot payload or server write is involved.
    """
    try:
        origins = github_repo_config.values(root, "remote.origin.url")
    except github_repo_config.GitHubRepoConfigError as exc:
        raise ProjectRepositoryIdentityError(compose_refusal(
            "project_repository_unreadable: checkout origin could not be read",
            recovery="Inspect this checkout's Git config, then retry",
        )) from exc
    if not origins or project is None:
        return
    binding = _binding_status(
        project, config_path=config_path, explicit_env=explicit_env,
        session_id=session_id, timeout_s=timeout_s,
    )
    if not binding:
        return
    expected = str(binding["github_repo"])
    web_url = github_web_url_from_api(str(binding["api_url"]))
    for origin in origins:
        try:
            actual = normalize_github_repository(origin, web_url=web_url)
        except GitHubApiOriginError:
            # Never echo an unparsed URL: it may contain a credential.
            actual = "unrecognized repository (inspect git remote get-url origin)"
        if actual.casefold() != expected.casefold():
            raise ProjectRepositoryIdentityError(compose_refusal(
                f"project_repository_mismatch: origin repository {actual} differs "
                f"from project {project}'s bound repository {expected}",
                recovery="Select the correct --project (or --project-id for install), "
                f"or run `git remote set-url origin {web_url}/{expected}.git`, then retry",
            ))


def _binding_status(project, *, config_path, explicit_env, session_id, timeout_s):
    from yoke_cli.commands._helpers import ensure_handlers_loaded
    from yoke_cli.transport.dispatcher import build_actor, call_dispatcher
    from yoke_contracts.api.function_call import TargetRef
    from yoke_contracts.machine_config.paths import select_read_config
    from yoke_cli.project_install.transport import _patched_env

    updates = {"YOKE_ENV": explicit_env} if explicit_env else {}
    with select_read_config(config_path), _patched_env(updates, set()):
        ensure_handlers_loaded()
        response = call_dispatcher(
            function_id="projects.github_binding.status",
            target=TargetRef(kind="global"),
            payload={"project": str(project)},
            actor=build_actor(session_id=session_id),
            timeout_s=timeout_s,
        )
    if not response.success:
        error = response.error
        raise ProjectRepositoryIdentityError(compose_refusal(
            "project_repository_binding_unavailable: "
            + (error.message if error else "binding status could not be read"),
            recovery="Check the selected project and connection with `yoke status`, then retry",
        ))
    return (response.result or {}).get("binding")


def assert_install_repository(root, project, *, config_path, explicit_env):
    """Translate identity refusals into the install surface's named error."""
    from yoke_cli.project_install.files import ProjectInstallError

    try:
        assert_project_repository(root, project, config_path=config_path, explicit_env=explicit_env)
    except ProjectRepositoryIdentityError as exc:
        raise ProjectInstallError(str(exc)) from exc
