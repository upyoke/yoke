"""Existing-local-checkout project onboarding orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from yoke_cli.config import machine_config
from yoke_cli.config import onboard_apply_progress
from yoke_cli.config import onboard_local_checkout_identity
from yoke_cli.config import project_checkout_path
from yoke_cli.config import project_clone_resume
from yoke_cli.config import project_onboard_apply
from yoke_cli.config import project_onboard_progress as progress_steps
from yoke_cli.config.project_github_adoption import (
    GITHUB_ADOPTION_APP_BINDING,
    github_adoption_report,
    github_sync_mode,
)
from yoke_cli.config.project_onboard_support import (
    ProjectDispatchError,
    ProjectOnboardError,
    dry_run_report,
    project_api_payload,
)
from yoke_cli.config.project_publish_support import PublishRequest


@dataclass(frozen=True)
class ExistingProjectOperations:
    """Patchable operations owned by the public project-onboard module."""

    create_and_publish: Callable[..., dict[str, Any]]
    dispatch: Callable[..., dict[str, Any]]
    finish_github_binding: Callable[..., Any]
    init_repo_if_needed: Callable[..., bool]
    is_git_repo: Callable[[Path], bool]
    publish_checkout_needed: Callable[[Path, PublishRequest], bool]
    record_selected_repository_identity: Callable[..., None]
    resumable_clone: Callable[..., bool]


def record_selected_repository_identity(
    github_adoption: dict[str, Any],
    publish: PublishRequest | None,
    *,
    repository_id: int | None = None,
    installation_id: int | None = None,
) -> None:
    """Carry an explicit existing-repository selection through final binding."""

    if publish is not None and not publish.create_repository:
        repository_id = publish.repository_id
        installation_id = publish.installation_id
    if repository_id is None and installation_id is None:
        return
    if (
        not isinstance(repository_id, int)
        or repository_id <= 0
        or not isinstance(installation_id, int)
        or installation_id <= 0
    ):
        raise ProjectOnboardError(
            "The selected existing repository identity is incomplete; check "
            "repositories again before Apply"
        )
    github_adoption["repository_id"] = repository_id
    github_adoption["installation_id"] = installation_id
    binding = dict(github_adoption.get("binding") or {})
    binding.update(
        {
            "repository_id": repository_id,
            "installation_id": installation_id,
        }
    )
    github_adoption["binding"] = binding


def onboard_existing(
    *,
    operations: ExistingProjectOperations,
    operation: str = "onboard.project",
    checkout: str | Path,
    slug: str,
    name: str,
    org: str | None,
    github_repo: str | None,
    github_repository_id: int | None = None,
    github_installation_id: int | None = None,
    default_branch: str,
    public_item_prefix: str,
    github_adoption_choice: str | None,
    config_path: str | Path | None,
    apply: bool,
    publish: PublishRequest | None = None,
    progress: onboard_apply_progress.ProgressCallback | None = None,
    checkout_action: str = "project-onboard-local-checkout",
    checkout_target: str | None = None,
    github_auth_target: str = "skip",
    reuse_checkout: bool = False,
    scaffold_action: str = "project-install-scaffold",
    reuse_github_auth: bool = False,
    existing_project_id: int | None = None,
    clone_remote_url: str | None = None,
    clone_token: str | None = None,
    clone_web_url: str | None = None,
    service_api_url: str | None = None,
    github_adoption_preserve: bool = False,
) -> dict[str, Any]:
    root = project_checkout_path.for_apply(
        checkout,
        error_type=ProjectOnboardError,
    )
    progress_target = checkout_target or str(root)
    if root.exists() and not root.is_dir():
        raise ProjectOnboardError(f"checkout is not a directory: {root}")
    if (
        root.is_dir()
        and operations.is_git_repo(root)
        and not project_clone_resume.is_exact_worktree_root(root)
    ):
        raise ProjectOnboardError(
            "checkout must be the exact Git worktree root, not a nested folder"
        )
    if (
        apply
        and github_repo
        and publish is None
        and github_adoption_choice == GITHUB_ADOPTION_APP_BINDING
    ):
        github = machine_config.github_config(config_path)
        try:
            onboard_local_checkout_identity.require_matching_origin(
                root,
                github_repo=github_repo,
                web_url=str(github.get("web_url") or "https://github.com"),
            )
        except RuntimeError as exc:
            raise ProjectOnboardError(str(exc)) from exc
    github_adoption = github_adoption_report(
        choice=github_adoption_choice,
        github_repo=github_repo,
        apply=apply,
        preserve_existing=github_adoption_preserve,
    )
    operations.record_selected_repository_identity(
        github_adoption,
        publish,
        repository_id=github_repository_id,
        installation_id=github_installation_id,
    )
    if not apply:
        return dry_run_report(
            repo_root=root,
            slug=slug,
            name=name,
            org=org,
            github_repo=github_repo,
            default_branch=default_branch,
            public_item_prefix=public_item_prefix,
            operation=operation,
            github_adoption=github_adoption,
            checkout_mode="existing-local" if root.is_dir() else "new-local",
        )
    project_onboard_apply.ensure_git_available()
    if not reuse_checkout:
        with onboard_apply_progress.step(progress, checkout_action, progress_target):
            if clone_remote_url:
                operations.resumable_clone(
                    root,
                    clone_remote_url,
                    token=clone_token,
                    github_web_url=clone_web_url,
                )
            else:
                root.mkdir(parents=True, exist_ok=True)
                operations.init_repo_if_needed(root, default_branch)
            if publish is not None and operations.publish_checkout_needed(
                root,
                publish,
            ):
                created = operations.create_and_publish(
                    root,
                    publish,
                    default_branch=default_branch,
                )
                github_repo = created["full_name"]
                progress_steps.record_mutated_repository(
                    github_adoption,
                    github_repo,
                    config_path,
                    service_api_url=service_api_url,
                )
    payload = project_api_payload(
        slug=slug,
        name=name,
        org=org,
        github_repo=github_repo,
        default_branch=default_branch,
        public_item_prefix=public_item_prefix,
        github_sync_mode=github_sync_mode(github_adoption),
    )
    with onboard_apply_progress.step(progress, scaffold_action):
        persist_sync_mode = True
        try:
            result = operations.dispatch(
                "projects.get",
                {
                    "project": project_onboard_apply.existing_project_key(
                        existing_project_id,
                        slug,
                    )
                },
                config_path,
            )
        except ProjectDispatchError as exc:
            if exc.code != "not_found":
                raise
            result = operations.dispatch("projects.create", payload, config_path)
            persist_sync_mode = False
        report = project_onboard_apply.finish_after_dispatch(
            operation=operation,
            root=root,
            result=result,
            github_adoption=github_adoption,
            config_path=config_path,
            progress=progress,
            github_auth_target=github_auth_target,
            scaffold_action=scaffold_action,
            reuse_github_auth=reuse_github_auth,
            register_mapping=True,
            persist_sync_mode=persist_sync_mode,
        )
    operations.finish_github_binding(
        progress,
        github_auth_target,
        github_adoption,
        reuse_github_auth,
    )
    return report
