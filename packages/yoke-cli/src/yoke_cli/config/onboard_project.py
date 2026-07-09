"""Project handoff helpers for the product ``yoke onboard`` wizard."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from yoke_cli.config import github_user_tokens
from yoke_cli.config import machine_config
from yoke_cli.config import onboard_apply_progress
from yoke_cli.config import project_onboard
from yoke_cli.config import secrets as machine_secrets
from yoke_cli.config.project_clone_support import ClonePlan
from yoke_cli.config.project_git_transport import https_remote
from yoke_cli.config.project_github_adoption import (
    GITHUB_ADOPTION_APP_BINDING,
    GITHUB_ADOPTION_BACKLOG_ONLY,
    ProjectGithubAdoptionError,
)
from yoke_cli.config.project_publish_support import PublishRequest
from yoke_cli.config.yoke_dev_access import YOKE_GITHUB_REPO
from yoke_cli.project_install.files import ProjectInstallError

# The branch a brand-new, empty repo is created with when there is no source to
# inherit one from. The create/publish flow offers this as the prompt default;
# the clone flow uses it only as a last-resort fallback when source detection
# fails. Single source of the literal so the prompt placeholder and the fallback
# never drift apart.
DEFAULT_NEW_REPO_BRANCH = "main"
DEFAULT_BRANCH_SOURCE_EXISTING_PROJECT = "existing-project"
DEFAULT_BRANCH_SOURCE_SOURCE_REPO = "source-repo"
DEFAULT_BRANCH_SOURCE_SOURCE_FALLBACK = "source-fallback"

PROJECT_MODE_MACHINE_ONLY = "machine-only"
PROJECT_MODE_CREATE_REPO = "create-repo"
PROJECT_MODE_CLONE_REMOTE = "clone-remote"
PROJECT_MODE_IMPORT_REMOTE = "import-remote"
PROJECT_MODE_LOCAL_CHECKOUT = "local-checkout"
PROJECT_MODE_SOURCE_DEV_ADMIN = "source-dev-admin"
PROJECT_REMOTE_MODES = (PROJECT_MODE_CLONE_REMOTE, PROJECT_MODE_IMPORT_REMOTE)
PROJECT_MODES = (
    PROJECT_MODE_MACHINE_ONLY,
    PROJECT_MODE_CREATE_REPO,
    PROJECT_MODE_CLONE_REMOTE,
    PROJECT_MODE_IMPORT_REMOTE,
    PROJECT_MODE_LOCAL_CHECKOUT,
    PROJECT_MODE_SOURCE_DEV_ADMIN,
)


class OnboardProjectError(RuntimeError):
    """The project handoff part of onboarding cannot proceed."""


def normalize_project_mode(project_mode: str | None) -> str:
    selected = (project_mode or PROJECT_MODE_MACHINE_ONLY).strip()
    if selected not in PROJECT_MODES:
        raise OnboardProjectError(
            f"unknown project mode {selected!r}; expected one of "
            f"{', '.join(PROJECT_MODES)}"
        )
    return selected


def project_inputs(
    *,
    project_mode: str,
    project_remote_url: str | None,
    project_checkout: str | Path | None,
    project_slug: str | None,
    project_name: str | None,
    project_org: str | None,
    project_github_repo: str | None,
    project_default_branch: str | None,
    project_public_item_prefix: str | None,
    existing_project_id: int | None,
    existing_project_match_source: str | None = None,
    existing_project_local_source: str | None = None,
    project_github_adoption: str | None = None,
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
    missing = [
        flag for flag, value in required.items() if not str(value or "").strip()
    ]
    if missing:
        raise OnboardProjectError(
            "missing required project onboarding flags: " + ", ".join(missing)
        )
    project_id = _normalize_existing_project_id(existing_project_id)
    return {
        "mode": project_mode,
        "remote_url": project_remote_url,
        "checkout": str(Path(str(project_checkout)).expanduser()),
        "slug": str(project_slug),
        "name": str(project_name),
        "org": project_org,
        "github_repo": project_github_repo,
        "default_branch": str(project_default_branch),
        "default_branch_source": str(project_default_branch_source or ""),
        "public_item_prefix": str(project_public_item_prefix),
        "existing_project_id": project_id,
        "existing_project_match_source": str(existing_project_match_source or ""),
        "existing_project_local_source": str(existing_project_local_source or ""),
        "github_adoption": project_github_adoption,
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


def _machine_github_token(config_path: Path) -> str | None:
    """A refreshed local GitHub App user token, or None — used to clone Yoke."""
    try:
        return github_user_tokens.refresh_from_machine_config(
            config_path=config_path,
        ).access_token
    except github_user_tokens.GitHubUserTokenError:
        return None


def project_report(
    *,
    config_path: Path,
    apply: bool,
    inputs: dict[str, Any],
    github_token: str | None,
    github_token_file: str | Path | None,
    github_token_stdin_value: str | None,
    reuse: Mapping[str, Any] | None = None,
    progress: onboard_apply_progress.ProgressCallback | None = None,
) -> dict[str, Any]:
    try:
        return _project_report(
            config_path=config_path,
            apply=apply,
            inputs=inputs,
            github_token=github_token,
            github_token_file=github_token_file,
            github_token_stdin_value=github_token_stdin_value,
            reuse=reuse,
            progress=progress,
        )
    except (
        ProjectGithubAdoptionError,
        ProjectInstallError,
        project_onboard.ProjectOnboardError,
        machine_secrets.MachineSecretError,
    ) as exc:
        raise OnboardProjectError(str(exc)) from exc


def _project_report(
    *,
    config_path: Path,
    apply: bool,
    inputs: dict[str, Any],
    github_token: str | None,
    github_token_file: str | Path | None,
    github_token_stdin_value: str | None,
    reuse: Mapping[str, Any] | None,
    progress: onboard_apply_progress.ProgressCallback | None,
) -> dict[str, Any]:
    kwargs = _project_kwargs(
        inputs=inputs,
        github_token=github_token,
        github_token_file=github_token_file,
        github_token_stdin_value=github_token_stdin_value,
        config_path=config_path,
        apply=apply,
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
        if reuse.get("project_scaffold") else
        "project-install-scaffold"
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
    if mode == PROJECT_MODE_SOURCE_DEV_ADMIN:
        # A fresh "Develop Yoke itself" folder is cloned from Yoke's own repo
        # (not git-init'd empty), authenticated with the machine GitHub
        # credential saved earlier in this apply.
        clone_remote_url = https_remote(YOKE_GITHUB_REPO)
        clone_token = _machine_github_token(config_path)
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
        **kwargs,
    )


def _github_auth_target(inputs: dict[str, Any], *, mode: str | None = None) -> str:
    """The github-auth review/apply target for a project mode.

    Single source of truth for both the apply path (``_project_report``) and the
    review plan (``onboard_report.build_plan``). ``mode`` overrides
    ``inputs["mode"]`` for callers that carry the project mode separately.
    """
    if inputs.get("existing_project_id"):
        return "existing-project"
    if inputs.get("keep_existing_remote"):
        return "keep-existing-remote"
    effective_mode = mode if mode is not None else str(inputs.get("mode") or "")
    if effective_mode == PROJECT_MODE_SOURCE_DEV_ADMIN:
        # Source-dev gets Yoke's GitHub remote from the clone, so it is neither a
        # "skip" (no remote) nor a per-project App binding.
        return "source-dev"
    selected = str(inputs.get("github_adoption") or "").strip()
    if selected in ("", "skip"):
        return (
            GITHUB_ADOPTION_APP_BINDING
            if inputs.get("github_repo")
            else GITHUB_ADOPTION_BACKLOG_ONLY
        )
    return selected


def _project_kwargs(
    *,
    inputs: dict[str, Any],
    github_token: str | None,
    github_token_file: str | Path | None,
    github_token_stdin_value: str | None,
    config_path: Path,
    apply: bool,
) -> dict[str, Any]:
    return {
        "checkout": inputs["checkout"],
        "slug": inputs["slug"],
        "name": inputs["name"],
        "org": inputs.get("org"),
        "github_repo": inputs.get("github_repo"),
        "default_branch": inputs["default_branch"],
        "public_item_prefix": inputs["public_item_prefix"],
        "existing_project_id": inputs.get("existing_project_id"),
        "github_token": github_token,
        "github_token_file": github_token_file,
        "github_token_stdin_value": github_token_stdin_value,
        "github_adoption_choice": inputs.get("github_adoption"),
        "config_path": config_path,
        "apply": apply,
    }


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
