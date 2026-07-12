"""New-local-checkout project creation orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from yoke_cli.config import onboard_apply_progress
from yoke_cli.config import project_checkout_path
from yoke_cli.config import project_onboard_apply
from yoke_cli.config import project_onboard_progress as progress_steps
from yoke_cli.config.project_github_adoption import (
    github_adoption_report,
    github_sync_mode,
)
from yoke_cli.config.project_onboard_support import (
    ProjectOnboardError,
    project_api_payload,
    project_dry_run,
)
from yoke_cli.config.project_publish_support import PublishRequest


@dataclass(frozen=True)
class CreateProjectOperations:
    """Patchable operations owned by the public project-onboard module."""

    create_and_publish: Callable[..., dict[str, Any]]
    dispatch: Callable[..., dict[str, Any]]
    finish_github_binding: Callable[..., Any]
    init_repo_if_needed: Callable[..., Any]
    publish_checkout_needed: Callable[[Path, PublishRequest], bool]
    record_selected_repository_identity: Callable[..., None]


def create_project(
    *,
    operations: CreateProjectOperations,
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
    checkout_action: str = "project-create-checkout",
    checkout_target: str | None = None,
    github_auth_target: str = "skip",
    scaffold_action: str = "project-install-scaffold",
    reuse_github_auth: bool = False,
    existing_project_id: int | None = None,
    service_api_url: str | None = None,
    local_connection_selected: bool = False,
    github_adoption_preserve: bool = False,
) -> dict[str, Any]:
    root = project_checkout_path.for_apply(
        checkout,
        error_type=ProjectOnboardError,
    )
    progress_target = checkout_target or str(root)
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
    payload = project_api_payload(
        slug=slug,
        name=name,
        org=org,
        github_repo=github_repo,
        default_branch=default_branch,
        public_item_prefix=public_item_prefix,
        github_sync_mode=github_sync_mode(github_adoption),
    )
    if not apply:
        return project_dry_run(
            "project.create",
            root,
            payload,
            "new-local",
            github_adoption,
        )

    project_onboard_apply.ensure_git_available()
    with onboard_apply_progress.step(progress, checkout_action, progress_target):
        root.mkdir(parents=True, exist_ok=True)
        operations.init_repo_if_needed(root, default_branch)
        if publish is not None and operations.publish_checkout_needed(root, publish):
            created = operations.create_and_publish(
                root,
                publish,
                default_branch=default_branch,
            )
            github_repo = created["full_name"]
            payload["github_repo"] = github_repo
            progress_steps.record_mutated_repository(
                github_adoption,
                github_repo,
                config_path,
                service_api_url=service_api_url,
                local_connection_selected=local_connection_selected,
            )
    with onboard_apply_progress.step(progress, scaffold_action):
        result = operations.dispatch("projects.create", payload, config_path)
        report = project_onboard_apply.finish_after_dispatch(
            operation="project.create",
            root=root,
            result=result,
            github_adoption=github_adoption,
            config_path=config_path,
            progress=progress,
            github_auth_target=github_auth_target,
            scaffold_action=scaffold_action,
            reuse_github_auth=reuse_github_auth,
            service_api_url=service_api_url,
            local_connection_selected=local_connection_selected,
        )
    operations.finish_github_binding(
        progress,
        github_auth_target,
        github_adoption,
        reuse_github_auth,
    )
    return report
