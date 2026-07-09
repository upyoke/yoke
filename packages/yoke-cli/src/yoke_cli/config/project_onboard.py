"""Product-safe project create/import/onboard orchestration."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from yoke_cli.config import onboard_apply_progress
from yoke_cli.config import project_onboard_apply
from yoke_cli.config import project_onboard_progress as progress_steps
from yoke_cli.config.project_github_adoption import (
    github_adoption_report,
)
from yoke_cli.config.project_onboard_support import (
    PLAN,
    ProjectDispatchError,
    ProjectOnboardError,
    dispatch,
    dry_run_report,
    github_token as resolve_github_token,
    project_api_payload,
    project_dry_run,
)
from yoke_cli.config.project_clone_support import ClonePlan
from yoke_cli.config import project_onboard_clone as apply_clone
from yoke_cli.config.project_publish_support import (
    PublishRequest,
    create_and_publish,
    init_repo_if_needed,
    publish_checkout_needed,
)

_resumable_clone = apply_clone.resumable_clone
_apply_clone_outcome = apply_clone.apply_clone_outcome


def _finish_github_binding(*args, **kwargs):
    # Bound lazily (not aliased at module load) so importing
    # project_onboard_apply as an entry point doesn't read this attribute
    # mid-cycle, before it is defined — project_onboard_apply imports
    # onboard_apply_progress -> onboard_project -> project_onboard.
    return project_onboard_apply.finish_github_binding_if_needed(*args, **kwargs)


def create_project(
    *,
    checkout: str | Path,
    slug: str,
    name: str,
    org: str | None,
    github_repo: str | None,
    default_branch: str,
    public_item_prefix: str,
    github_token: str | None,
    github_token_file: str | Path | None,
    github_token_stdin_value: str | None,
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
) -> dict[str, Any]:
    root = Path(checkout).expanduser().resolve()
    progress_target = checkout_target or str(root)
    token_value, token_import_method = resolve_github_token(
        token=github_token,
        token_file=github_token_file,
        token_stdin_value=github_token_stdin_value,
    )
    github_adoption = github_adoption_report(
        choice=github_adoption_choice,
        github_repo=github_repo,
        token_value=token_value,
        token_import_method=token_import_method,
        apply=apply,
    )
    payload = project_api_payload(
        slug=slug, name=name, org=org,
        github_repo=github_repo, default_branch=default_branch,
        public_item_prefix=public_item_prefix,
    )
    if not apply:
        return project_dry_run(
            "project.create", root, payload, "new-local", github_adoption,
        )

    project_onboard_apply.ensure_git_available()
    with onboard_apply_progress.step(progress, checkout_action, progress_target):
        root.mkdir(parents=True, exist_ok=True)
        init_repo_if_needed(root, default_branch)
        if publish is not None and publish_checkout_needed(root, publish):
            created = create_and_publish(root, publish, default_branch=default_branch)
            github_repo = created["full_name"]
            payload["github_repo"] = github_repo
    with onboard_apply_progress.step(progress, scaffold_action):
        result = dispatch("projects.create", payload, config_path)
        report = project_onboard_apply.finish_after_dispatch(
            operation="project.create",
            root=root,
            result=result,
            github_adoption=github_adoption,
            config_path=config_path,
            progress=progress,
            github_auth_target=github_auth_target,
            token_value=token_value,
            scaffold_action=scaffold_action,
            reuse_github_auth=reuse_github_auth,
        )
    _finish_github_binding(progress, github_auth_target, github_adoption, reuse_github_auth)
    return report


def import_project(
    *,
    remote_url: str,
    checkout: str | Path,
    slug: str,
    name: str,
    org: str | None,
    github_repo: str | None,
    default_branch: str,
    public_item_prefix: str,
    github_token: str | None,
    github_token_file: str | Path | None,
    github_token_stdin_value: str | None,
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
) -> dict[str, Any]:
    plan = clone or ClonePlan()
    root = Path(checkout).expanduser().resolve()
    progress_target = checkout_target or str(root)
    token_value, token_import_method = resolve_github_token(
        token=github_token,
        token_file=github_token_file,
        token_stdin_value=github_token_stdin_value,
    )
    github_adoption = github_adoption_report(
        choice=github_adoption_choice,
        github_repo=github_repo,
        token_value=token_value,
        token_import_method=token_import_method,
        apply=apply,
    )
    payload = project_api_payload(
        slug=slug, name=name, org=org,
        github_repo=github_repo, default_branch=default_branch,
        public_item_prefix=public_item_prefix,
    )
    if not apply:
        if existing_project_id is not None:
            return project_dry_run(
                "project.clone-existing", root, payload, "clone-existing",
                github_adoption,
            )
        return project_dry_run(
            "project.import", root, payload, "clone-remote", github_adoption,
        )

    project_onboard_apply.ensure_git_available()
    if reuse_checkout:
        outcome = None
    else:
        onboard_apply_progress.emit(progress, checkout_action, progress_target, "running")
        try:
            clone_reused = _resumable_clone(root, remote_url, token=plan.fallback_token)
        except Exception:
            onboard_apply_progress.emit(progress, checkout_action, progress_target, "failed")
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
                    root, remote_url=remote_url, default_branch=default_branch,
                    plan=plan, clone_reused=clone_reused,
                )
        else:
            outcome = _apply_clone_outcome(
                root, remote_url=remote_url, default_branch=default_branch, plan=plan,
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
            token_value=token_value,
            clone_outcome=outcome,
            scaffold_action=scaffold_action,
            reuse_github_auth=reuse_github_auth,
        )
    if outcome is not None and outcome.github_repo is not None:
        github_repo = outcome.github_repo
        payload["github_repo"] = outcome.github_repo
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
            token_value=token_value,
            scaffold_action=scaffold_action,
            reuse_github_auth=reuse_github_auth,
            clone_outcome=outcome,
        )
    _finish_github_binding(progress, github_auth_target, github_adoption, reuse_github_auth)
    return report


def onboard_existing(
    *,
    operation: str = "onboard.project",
    checkout: str | Path,
    slug: str,
    name: str,
    org: str | None,
    github_repo: str | None,
    default_branch: str,
    public_item_prefix: str,
    github_token: str | None,
    github_token_file: str | Path | None,
    github_token_stdin_value: str | None,
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
) -> dict[str, Any]:
    root = Path(checkout).expanduser().resolve()
    progress_target = checkout_target or str(root)
    # A not-yet-existing path is fine — onboarding creates the folder and a git
    # repo at apply, mirroring create_project. Only a path that exists as a
    # regular file (not a directory) is a hard error: Yoke cannot make a
    # checkout out of a plain file.
    if root.exists() and not root.is_dir():
        raise ProjectOnboardError(f"checkout is not a directory: {root}")
    token_value, token_import_method = resolve_github_token(
        token=github_token,
        token_file=github_token_file,
        token_stdin_value=github_token_stdin_value,
    )
    github_adoption = github_adoption_report(
        choice=github_adoption_choice,
        github_repo=github_repo,
        token_value=token_value,
        token_import_method=token_import_method,
        apply=apply,
    )
    if not apply:
        return dry_run_report(
            repo_root=root, slug=slug, name=name, org=org,
            github_repo=github_repo,
            default_branch=default_branch, public_item_prefix=public_item_prefix,
            operation=operation,
            github_adoption=github_adoption,
            # A missing folder reads as one Yoke will create, the same way
            # create_project's dry-run reports a fresh checkout.
            checkout_mode="existing-local" if root.is_dir() else "new-local",
        )
    project_onboard_apply.ensure_git_available()
    # An existing folder may not be a git repo yet, and a missing folder must be
    # created — make the directory and lay down a git repo (the mode's own copy
    # promises "Yoke makes it a git repo if it isn't"), parity with
    # create_project, before any GitHub or dispatch step.
    if not reuse_checkout:
        with onboard_apply_progress.step(progress, checkout_action, progress_target):
            if clone_remote_url:
                # "Develop Yoke itself" into a fresh folder: clone the real repo
                # so the checkout holds Yoke's source and its origin remote,
                # instead of an empty git init. resumable_clone reuses a folder
                # that is already this clone and errors on a conflicting one.
                _resumable_clone(root, clone_remote_url, token=clone_token)
            else:
                root.mkdir(parents=True, exist_ok=True)
                init_repo_if_needed(root, default_branch)
            if publish is not None and publish_checkout_needed(root, publish):
                # Publishing creates the GitHub repo and pushes; the repo is already a
                # git repo by now. Unrelated remotes are skipped, while a matching
                # origin resumes a prior create-then-push attempt.
                created = create_and_publish(root, publish, default_branch=default_branch)
                github_repo = created["full_name"]
    payload = project_api_payload(
        slug=slug, name=name, org=org,
        github_repo=github_repo, default_branch=default_branch,
        public_item_prefix=public_item_prefix,
    )
    with onboard_apply_progress.step(progress, scaffold_action):
        try:
            result = dispatch(
                "projects.get",
                {
                    "project": project_onboard_apply.existing_project_key(
                        existing_project_id, slug,
                    )
                },
                config_path,
            )
        except ProjectDispatchError as exc:
            if exc.code != "not_found":
                raise
            result = dispatch("projects.create", payload, config_path)
        report = project_onboard_apply.finish_after_dispatch(
            operation=operation,
            root=root,
            result=result,
            github_adoption=github_adoption,
            config_path=config_path,
            progress=progress,
            github_auth_target=github_auth_target,
            token_value=token_value,
            scaffold_action=scaffold_action,
            reuse_github_auth=reuse_github_auth,
            register_mapping=True,
        )
    _finish_github_binding(progress, github_auth_target, github_adoption, reuse_github_auth)
    return report

__all__ = [
    "PLAN",
    "ClonePlan",
    "ProjectOnboardError",
    "PublishRequest",
    "create_project",
    "dry_run_report",
    "import_project",
    "onboard_existing",
]
