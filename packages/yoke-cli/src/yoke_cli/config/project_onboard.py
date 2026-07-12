"""Product-safe project create/import/onboard orchestration."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from yoke_cli.config import onboard_apply_progress
from yoke_cli.config import project_checkout_path
from yoke_cli.config import project_clone_resume
from yoke_cli.config import project_onboard_apply
from yoke_cli.config import project_onboard_create
from yoke_cli.config import project_onboard_existing
from yoke_cli.config import project_onboard_progress as progress_steps
from yoke_cli.config.project_github_adoption import (
    github_adoption_report,
    github_sync_mode,
)
from yoke_cli.config.project_onboard_support import (
    PLAN,
    ProjectDispatchError,
    ProjectOnboardError,
    dispatch,
    dry_run_report,
    project_api_payload,
    project_dry_run,
)
from yoke_cli.config.project_clone_support import ClonePlan
from yoke_cli.config import project_onboard_clone as apply_clone
from yoke_cli.config.project_onboard_existing import (
    record_selected_repository_identity as _record_selected_repository_identity,
)
from yoke_cli.config.project_publish_support import (
    PublishRequest,
    create_and_publish,
    init_repo_if_needed,
    is_git_repo,
    publish_checkout_needed,
)

_resumable_clone = apply_clone.resumable_clone
_apply_clone_outcome = apply_clone.apply_clone_outcome


def _finish_github_binding(*args, **kwargs):
    # Bound lazily because project_onboard_apply participates in this import cycle.
    return project_onboard_apply.finish_github_binding_if_needed(*args, **kwargs)


def create_project(
    *,
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
    return project_onboard_create.create_project(
        operations=project_onboard_create.CreateProjectOperations(
            create_and_publish=create_and_publish,
            dispatch=dispatch,
            finish_github_binding=_finish_github_binding,
            init_repo_if_needed=init_repo_if_needed,
            publish_checkout_needed=publish_checkout_needed,
            record_selected_repository_identity=(_record_selected_repository_identity),
        ),
        **locals(),
    )


def import_project(
    *,
    remote_url: str,
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
    clone: ClonePlan | None = None,
    progress: onboard_apply_progress.ProgressCallback | None = None,
    checkout_action: str = "project-clone-remote",
    checkout_target: str | None = None,
    github_auth_target: str = "skip",
    reuse_checkout: bool = False,
    scaffold_action: str = "project-install-scaffold",
    reuse_github_auth: bool = False,
    existing_project_id: int | None = None,
    service_api_url: str | None = None,
    local_connection_selected: bool = False,
    github_adoption_preserve: bool = False,
) -> dict[str, Any]:
    requested_plan, remote_url = apply_clone.normalize_clone_request(
        remote_url,
        clone,
    )
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
        if existing_project_id is not None:
            return project_dry_run(
                "project.clone-existing",
                root,
                payload,
                "clone-existing",
                github_adoption,
            )
        return project_dry_run(
            "project.import",
            root,
            payload,
            "clone-remote",
            github_adoption,
        )

    plan = apply_clone.prepare_clone_plan(
        requested_plan,
        config_path,
        remote_url=remote_url,
        service_api_url=service_api_url,
        local_connection_selected=local_connection_selected,
    )
    _record_selected_repository_identity(
        github_adoption,
        plan.publish,
        repository_id=github_repository_id,
        installation_id=github_installation_id,
    )
    project_onboard_apply.ensure_git_available()
    if reuse_checkout:
        if not project_clone_resume.existing_clone_matches(
            root,
            remote_url,
            web_url=plan.fork_web_url,
        ):
            raise ProjectOnboardError(
                "the reused checkout is no longer the exact worktree and remote "
                "selected for this onboarding run"
            )
        outcome = None
    else:
        onboard_apply_progress.emit(
            progress, checkout_action, progress_target, "running"
        )
        try:
            clone_reused = apply_clone.resumable_clone_with_machine_fallback(
                root,
                remote_url,
                plan=plan,
                config_path=config_path,
                service_api_url=service_api_url,
                local_connection_selected=local_connection_selected,
                clone=_resumable_clone,
            )
        except Exception:
            onboard_apply_progress.emit(
                progress, checkout_action, progress_target, "failed"
            )
            raise
        onboard_apply_progress.emit(
            progress,
            checkout_action,
            progress_target,
            "skipped" if clone_reused else "done",
        )
        outcome_action = progress_steps.clone_outcome_action(plan)
        if outcome_action:
            with onboard_apply_progress.step(progress, outcome_action):
                outcome = _apply_clone_outcome(
                    root,
                    remote_url=remote_url,
                    default_branch=default_branch,
                    plan=plan,
                    clone_reused=clone_reused,
                )
        else:
            outcome = _apply_clone_outcome(
                root,
                remote_url=remote_url,
                default_branch=default_branch,
                plan=plan,
                clone_reused=clone_reused,
            )
    if existing_project_id is not None:
        return project_onboard_apply.install_existing_project(
            operation="project.clone-existing",
            root=root,
            project_key=str(existing_project_id),
            github_adoption=github_adoption,
            config_path=config_path,
            progress=progress,
            github_auth_target=github_auth_target,
            clone_outcome=outcome,
            scaffold_action=scaffold_action,
            reuse_github_auth=reuse_github_auth,
            service_api_url=service_api_url,
            local_connection_selected=local_connection_selected,
        )
    if outcome is not None and outcome.github_repo is not None:
        github_repo = outcome.github_repo
        payload["github_repo"] = outcome.github_repo
        progress_steps.record_mutated_repository(
            github_adoption,
            outcome.github_repo,
            config_path,
            service_api_url=service_api_url,
            local_connection_selected=local_connection_selected,
        )
    if outcome is not None and outcome.branch is not None:
        default_branch = outcome.branch
        payload["default_branch"] = outcome.branch
    with onboard_apply_progress.step(progress, scaffold_action):
        result = dispatch("projects.create", payload, config_path)
        report = project_onboard_apply.finish_after_dispatch(
            operation="project.import",
            root=root,
            result=result,
            github_adoption=github_adoption,
            config_path=config_path,
            progress=progress,
            github_auth_target=github_auth_target,
            scaffold_action=scaffold_action,
            reuse_github_auth=reuse_github_auth,
            clone_outcome=outcome,
            service_api_url=service_api_url,
            local_connection_selected=local_connection_selected,
        )
    _finish_github_binding(
        progress, github_auth_target, github_adoption, reuse_github_auth
    )
    return report


def onboard_existing(
    *,
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
    local_connection_selected: bool = False,
    github_adoption_preserve: bool = False,
) -> dict[str, Any]:
    return project_onboard_existing.onboard_existing(
        operations=project_onboard_existing.ExistingProjectOperations(
            create_and_publish=create_and_publish,
            dispatch=dispatch,
            finish_github_binding=_finish_github_binding,
            init_repo_if_needed=init_repo_if_needed,
            is_git_repo=is_git_repo,
            publish_checkout_needed=publish_checkout_needed,
            record_selected_repository_identity=(_record_selected_repository_identity),
            resumable_clone=_resumable_clone,
        ),
        **locals(),
    )


__all__ = [
    "PLAN",
    "ClonePlan",
    "ProjectDispatchError",
    "ProjectOnboardError",
    "PublishRequest",
    "create_project",
    "dry_run_report",
    "import_project",
    "onboard_existing",
]
