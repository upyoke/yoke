"""Project handoff helpers for the product ``yoke onboard`` wizard."""

from __future__ import annotations

from pathlib import Path
import re
from typing import Any, Mapping

from yoke_contracts import github_origin
from yoke_cli.config import github_local_user_access, machine_config
from yoke_cli.config import onboard_apply_progress, onboard_project_github_inputs
from yoke_cli.config import project_onboard
from yoke_cli.config.onboard_project_modes import (
    DEFAULT_BRANCH_SOURCE_EXISTING_PROJECT as DEFAULT_BRANCH_SOURCE_EXISTING_PROJECT,
    DEFAULT_BRANCH_SOURCE_SOURCE_FALLBACK as DEFAULT_BRANCH_SOURCE_SOURCE_FALLBACK,
    DEFAULT_BRANCH_SOURCE_SOURCE_REPO as DEFAULT_BRANCH_SOURCE_SOURCE_REPO,
    DEFAULT_NEW_REPO_BRANCH,
    OnboardProjectError,
    PROJECT_MODE_CLONE_REMOTE,
    PROJECT_MODE_CREATE_REPO,
    PROJECT_MODE_IMPORT_REMOTE,
    PROJECT_MODE_LOCAL_CHECKOUT,
    PROJECT_MODE_MACHINE_ONLY,
    PROJECT_MODE_SOURCE_DEV_ADMIN,
    PROJECT_MODES,
    PROJECT_REMOTE_MODES,
    normalize_project_mode,
)
from yoke_cli.config.onboard_project_report import (
    github_auth_target as _github_auth_target,
    project_kwargs as _project_kwargs,
)
from yoke_cli.config.project_clone_support import ClonePlan
from yoke_cli.config.project_git_transport import clean_remote_url, https_remote
from yoke_cli.config.project_github_adoption import (
    ProjectGithubAdoptionError,
)
from yoke_cli.config.project_publish_support import PublishRequest
from yoke_cli.config.yoke_dev_access import YOKE_GITHUB_REPO
from yoke_cli.project_install.files import ProjectInstallError


def project_inputs(
    *,
    project_mode: str,
    project_remote_url: str | None,
    project_checkout: str | Path | None,
    project_slug: str | None,
    project_name: str | None,
    project_org: str | None,
    project_github_repo: str | None,
    project_github_repository_id: int | None = None,
    project_github_installation_id: int | None = None,
    project_default_branch: str | None,
    project_public_item_prefix: str | None,
    existing_project_id: int | None,
    existing_project_match_source: str | None = None,
    existing_project_local_source: str | None = None,
    project_github_adoption: str | None = None,
    project_github_adoption_preserve: bool = False,
    project_publish: PublishRequest | None = None,
    project_clone: ClonePlan | None = None,
    project_keep_existing_remote: bool = False,
    project_default_branch_source: str | None = None,
) -> dict[str, Any]:
    if project_mode == PROJECT_MODE_MACHINE_ONLY:
        return {}
    required = {
        "--checkout": project_checkout,
        "--project-slug": project_slug,
        "--project-name": project_name,
        "--default-branch": project_default_branch,
        "--public-item-prefix": project_public_item_prefix,
    }
    if project_mode in PROJECT_REMOTE_MODES:
        required["--remote-url"] = project_remote_url
    # --github-repo is never a precondition for create-repo. The repo arrives one
    # of three ways, each handled downstream: publishing creates it at apply;
    # app binding validates an existing repo once selected; declining both
    # yields a valid local-only project with no remote.
    missing = [flag for flag, value in required.items() if not str(value or "").strip()]
    if missing:
        raise OnboardProjectError(
            "missing required project onboarding flags: " + ", ".join(missing)
        )
    project_id = _normalize_existing_project_id(existing_project_id)
    preserve_github_adoption = bool(
        project_github_adoption_preserve
        or (project_id is not None and project_github_adoption is None)
    )
    normalized_remote_url = _normalized_remote_url(
        project_remote_url,
        project_mode=project_mode,
        project_clone=project_clone,
    )
    return {
        "mode": project_mode,
        "remote_url": normalized_remote_url,
        "checkout": str(Path(str(project_checkout)).expanduser()),
        "slug": str(project_slug),
        "name": str(project_name),
        "org": project_org,
        "github_repo": project_github_repo,
        "github_repository_id": project_github_repository_id,
        "github_installation_id": project_github_installation_id,
        "default_branch": str(project_default_branch),
        "default_branch_source": str(project_default_branch_source or ""),
        "public_item_prefix": str(project_public_item_prefix),
        "existing_project_id": project_id,
        "existing_project_match_source": str(existing_project_match_source or ""),
        "existing_project_local_source": str(existing_project_local_source or ""),
        "github_adoption": project_github_adoption,
        "github_adoption_preserve": preserve_github_adoption,
        "publish": project_publish,
        "clone": project_clone,
        "keep_existing_remote": project_keep_existing_remote,
    }


def _normalize_existing_project_id(value: int | None) -> int | None:
    if value is None:
        return None
    try:
        numeric = int(value)
    except (TypeError, ValueError) as exc:
        raise OnboardProjectError("existing_project_id must be numeric") from exc
    if numeric <= 0:
        raise OnboardProjectError("existing_project_id must be positive")
    return numeric


def _normalized_remote_url(
    value: str | None,
    *,
    project_mode: str,
    project_clone: ClonePlan | None,
) -> str | None:
    if project_mode not in PROJECT_REMOTE_MODES:
        return value
    raw = str(value or "").strip()
    # Source-development tests and admin use can intentionally clone a local
    # path. Network remotes, however, cross the GitHub boundary and must be
    # canonicalized before any preview or durable report can render them.
    network_shaped = (
        "://" in raw or "@" in raw or re.match(r"^[^/\\]+:[^/\\]", raw) is not None
    )
    if not network_shaped:
        return raw
    web_url = (
        str(project_clone.fork_web_url or "")
        if isinstance(project_clone, ClonePlan)
        else ""
    ) or github_origin.DEFAULT_GITHUB_WEB_URL
    try:
        return clean_remote_url(raw, web_url=web_url)
    except project_onboard.ProjectOnboardError as exc:
        raise OnboardProjectError(str(exc)) from exc


def _github_user_access_token(config_path: Path) -> str | None:
    """A refreshed local GitHub App user token, or None — used to clone Yoke."""
    try:
        return github_local_user_access.access_token(
            config_path=config_path
        ).access_token
    except github_local_user_access.GitHubLocalUserAccessError:
        return None


def project_report(
    *,
    config_path: Path,
    apply: bool,
    inputs: dict[str, Any],
    reuse: Mapping[str, Any] | None = None,
    progress: onboard_apply_progress.ProgressCallback | None = None,
    service_api_url: str | None = None,
) -> dict[str, Any]:
    try:
        return _project_report(
            config_path=config_path,
            apply=apply,
            inputs=inputs,
            reuse=reuse,
            progress=progress,
            service_api_url=service_api_url,
        )
    except (
        ProjectGithubAdoptionError,
        ProjectInstallError,
        onboard_project_github_inputs.MachineGitHubInputError,
        project_onboard.ProjectOnboardError,
    ) as exc:
        raise OnboardProjectError(str(exc)) from exc


def _project_report(
    *,
    config_path: Path,
    apply: bool,
    inputs: dict[str, Any],
    reuse: Mapping[str, Any] | None,
    progress: onboard_apply_progress.ProgressCallback | None,
    service_api_url: str | None = None,
) -> dict[str, Any]:
    if apply:
        inputs = onboard_project_github_inputs.hydrate_machine_github_inputs(
            inputs, config_path
        )
    kwargs = _project_kwargs(
        inputs=inputs,
        config_path=config_path,
        apply=apply,
        service_api_url=service_api_url,
    )
    mode = str(inputs.get("mode") or PROJECT_MODE_LOCAL_CHECKOUT)
    publish = inputs.get("publish")
    checkout_action = onboard_apply_progress.project_action_for_mode(mode)
    checkout_target = str(inputs.get("checkout") or "")
    github_auth_target = _github_auth_target(inputs)
    reuse = dict(reuse or {})
    reuse_checkout = bool(reuse.get("project_checkout"))
    reuse_github_auth = bool(reuse.get("project_github_auth"))
    scaffold_action = (
        "project-refresh-scaffold"
        if reuse.get("project_scaffold")
        else "project-install-scaffold"
    )
    if mode == PROJECT_MODE_CREATE_REPO:
        return project_onboard.create_project(
            publish=publish,
            progress=progress,
            checkout_action=checkout_action,
            checkout_target=checkout_target,
            github_auth_target=github_auth_target,
            scaffold_action=scaffold_action,
            reuse_github_auth=reuse_github_auth,
            **kwargs,
        )
    if mode in PROJECT_REMOTE_MODES:
        # A clone always brings its own remote; the post-clone outcome (just
        # clone / make it mine / fork) is carried in the clone plan.
        return project_onboard.import_project(
            remote_url=str(inputs["remote_url"]),
            clone=inputs.get("clone"),
            progress=progress,
            checkout_action=checkout_action,
            checkout_target=checkout_target,
            github_auth_target=github_auth_target,
            reuse_checkout=reuse_checkout,
            scaffold_action=scaffold_action,
            reuse_github_auth=reuse_github_auth,
            **kwargs,
        )
    # Imported here, not at module top, to avoid a load-time import cycle:
    # project_onboard_apply -> onboard_apply_progress -> onboard_project.
    from yoke_cli.config.project_onboard_apply import SOURCE_DEV_ADMIN_OPERATION

    operation = (
        SOURCE_DEV_ADMIN_OPERATION
        if mode == PROJECT_MODE_SOURCE_DEV_ADMIN
        else "onboard.project"
    )
    clone_remote_url: str | None = None
    clone_token: str | None = None
    clone_web_url: str | None = None
    if mode == PROJECT_MODE_SOURCE_DEV_ADMIN:
        # A fresh "Develop Yoke itself" folder is cloned from Yoke's own repo
        # (not git-init'd empty), authenticated with the machine GitHub
        # credential saved earlier in this apply.
        github_config = machine_config.github_config(config_path)
        clone_web_url = github_origin.DEFAULT_GITHUB_WEB_URL
        clone_remote_url = https_remote(
            YOKE_GITHUB_REPO,
            web_url=clone_web_url,
        )
        configured_web = github_origin.validate_github_web_endpoint(
            str(github_config.get("web_url") or clone_web_url)
        )
        if configured_web.origin == clone_web_url:
            clone_token = _github_user_access_token(config_path)
    return project_onboard.onboard_existing(
        operation=operation,
        publish=publish,
        progress=progress,
        checkout_action=checkout_action,
        checkout_target=checkout_target,
        github_auth_target=github_auth_target,
        reuse_checkout=reuse_checkout,
        scaffold_action=scaffold_action,
        reuse_github_auth=reuse_github_auth,
        clone_remote_url=clone_remote_url,
        clone_token=clone_token,
        clone_web_url=clone_web_url,
        **kwargs,
    )


def preflight_project_apply(project_report: Any) -> None:
    if not isinstance(project_report, dict):
        return
    github_adoption = project_report.get("github_adoption")
    if not isinstance(github_adoption, dict):
        return
    if github_adoption.get("requires_explicit_choice"):
        raise OnboardProjectError(
            "choose --github-adoption app-binding or backlog-only before "
            "applying GitHub project adoption"
        )


__all__ = [
    "ClonePlan",
    "DEFAULT_NEW_REPO_BRANCH",
    "OnboardProjectError",
    "PROJECT_MODE_CLONE_REMOTE",
    "PROJECT_MODE_CREATE_REPO",
    "PROJECT_MODE_IMPORT_REMOTE",
    "PROJECT_MODE_LOCAL_CHECKOUT",
    "PROJECT_MODE_MACHINE_ONLY",
    "PROJECT_MODE_SOURCE_DEV_ADMIN",
    "PROJECT_MODES",
    "PublishRequest",
    "normalize_project_mode",
    "preflight_project_apply",
    "project_inputs",
    "project_report",
]
