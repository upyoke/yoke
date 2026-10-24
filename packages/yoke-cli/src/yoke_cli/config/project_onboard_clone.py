"""Resumable checkout and publication-destination choreography."""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Callable

from yoke_cli.config import github_local_user_access, github_publish, machine_config
from yoke_cli.config import github_fork_access
from yoke_cli.config import project_clone_fork_resume
from yoke_cli.config.project_clone_resume import existing_clone_matches
from yoke_cli.config.project_clone_support import (
    CLONE_OUTCOME_FORK,
    CLONE_OUTCOME_JUST_CLONE,
    CLONE_OUTCOME_SOURCE,
    CLONE_OUTCOME_MAKE_IT_MINE,
    ClonePlan,
    clone_with_connected_access,
    origin_is,
    rehome_to_new_origin,
    set_fork_remotes,
    source_owner_repo,
)
from yoke_cli.config.project_git_transport import (
    clean_remote_url,
    git_current_branch,
    https_remote,
)
from yoke_cli.config.project_onboard_support import (
    ProjectOnboardError,
    ensure_new_checkout,
)
from yoke_cli.config.project_publish_support import local_head_sha


def prepare_clone_plan(
    plan: ClonePlan,
    config_path: str | Path | None,
    *,
    remote_url: str | None = None,
    service_api_url: str | None = None,
    local_connection_selected: bool = False,
) -> ClonePlan:
    if (
        plan.fallback_token is None
        and plan.use_machine_github
        and plan.outcome in (CLONE_OUTCOME_FORK, CLONE_OUTCOME_MAKE_IT_MINE)
    ):
        try:
            token = github_local_user_access.access_token(
                config_path=config_path,
                service_api_url=service_api_url,
                local_connection_selected=local_connection_selected,
            )
        except github_local_user_access.GitHubLocalUserAccessError as exc:
            raise ProjectOnboardError(
                "Connected GitHub App authorization could not be refreshed for "
                "the clone. Run `yoke github connect` again, or disconnect it "
                "before cloning a public repository."
            ) from exc
        plan = replace(plan, fallback_token=token.access_token)
    github_config = machine_config.github_config(config_path)
    if github_config:
        reason = github_fork_access.unavailable_reason(github_config, remote_url)
        plan = replace(
            plan, fork_web_url=str(github_config.get("web_url") or plan.fork_web_url),
            fork_allowed=not reason if plan.outcome == CLONE_OUTCOME_FORK else plan.fork_allowed,
            fork_unavailable_reason=reason if plan.outcome == CLONE_OUTCOME_FORK else "",
        )
    return plan


def normalize_clone_request(
    remote_url: str,
    plan: ClonePlan | None,
) -> tuple[ClonePlan, str]:
    """Return a plan and its credential-free canonical source URL."""

    selected = plan or ClonePlan()
    return selected, clean_remote_url(
        remote_url, web_url=selected.fork_web_url,
    )


def machine_token_provider(
    plan: ClonePlan,
    config_path: str | Path | None,
    *,
    service_api_url: str | None = None,
    local_connection_selected: bool = False,
) -> Callable[[], str | None] | None:
    """Return a lazy token source for a clone that reads through GitHub access."""
    if not plan.use_machine_github or plan.fallback_token:
        return None

    def provide() -> str:
        try:
            return github_local_user_access.access_token(
                config_path=config_path,
                service_api_url=service_api_url,
                local_connection_selected=local_connection_selected,
            ).access_token
        except github_local_user_access.GitHubLocalUserAccessError as exc:
            raise ProjectOnboardError(
                "Connected GitHub App authorization could not be refreshed for "
                "the clone. Reconnect GitHub and retry."
            ) from exc

    return provide


@dataclass(frozen=True)
class CloneApplyResult:
    """Clone result plus which idempotent steps reused prior-run state."""

    github_repo: str | None
    branch: str | None
    clone_reused: bool = False
    repo_reused: bool = False
    origin_rehomed: bool = False
    publication_read_only: bool | None = None


def resumable_clone(
    root: Path,
    remote_url: str,
    *,
    token: str | None,
    token_provider: Callable[[], str | None] | None = None,
    github_web_url: str | None = None,
) -> bool:
    """Reuse an exact matching checkout, or clone into a new empty target."""
    clean_remote = clean_remote_url(remote_url, web_url=github_web_url)
    if existing_clone_matches(
        root, clean_remote, web_url=github_web_url,
    ):
        return True
    if root.exists() and any(root.iterdir()):
        raise ProjectOnboardError(
            f"{root} already has files but isn't a clone of this repo. Re-run "
            "and pick an empty folder to resume cleanly, or remove "
            f"{root} to start over."
        )
    ensure_new_checkout(root)
    clone_with_connected_access(
        root.parent, root.name, clean_remote,
        token=token, token_provider=token_provider,
        github_web_url=github_web_url,
    )
    return False


def resumable_clone_with_machine_access(
    root: Path,
    remote_url: str,
    *,
    plan: ClonePlan,
    config_path: str | Path | None,
    service_api_url: str | None = None,
    local_connection_selected: bool = False,
    clone: Callable[..., bool] = resumable_clone,
) -> bool:
    """Clone through the connected GitHub access when the plan resolves one."""

    return clone(
        root,
        remote_url,
        token=plan.fallback_token,
        token_provider=machine_token_provider(
            plan,
            config_path,
            service_api_url=service_api_url,
            local_connection_selected=local_connection_selected,
        ),
        github_web_url=plan.fork_web_url,
    )


def apply_clone_outcome(
    root: Path,
    *,
    remote_url: str,
    default_branch: str,
    plan: ClonePlan,
    clone_reused: bool = False,
) -> CloneApplyResult:
    """Apply the selected destination to a new or independently cloned checkout."""
    from yoke_cli.config import project_publication_destination as destination

    if plan.outcome in (CLONE_OUTCOME_JUST_CLONE, CLONE_OUTCOME_SOURCE) and not origin_is(
        root, remote_url, web_url=plan.fork_web_url,
    ):
        raise ProjectOnboardError(
            "publication_destination_changed: the source origin changed after selection. "
            "Restore the selected source or re-run setup to review its actual destination."
        )
    if plan.outcome == CLONE_OUTCOME_MAKE_IT_MINE and plan.publish is None:
        raise ProjectOnboardError(
            "publication_destination_unresolved: Duplicate needs a selected "
            "writable repository. Re-run setup and select its destination."
        )
    elif plan.outcome == CLONE_OUTCOME_FORK and not plan.fallback_token:
        raise ProjectOnboardError(
            "publication_destination_unresolved: Fork needs GitHub authorization. "
            "Connect GitHub and choose Fork again, or select read-only."
        )
    if plan.outcome == CLONE_OUTCOME_MAKE_IT_MINE and plan.publish is not None:
        expected_origin = https_remote(
            plan.publish.full_name, web_url=plan.publish.web_url,
        )
        destination.require_published_source(root, expected_origin, plan.fork_web_url)
        expected_head_sha = local_head_sha(root, default_branch)
        if not plan.publish.create_repository:
            if (
                not isinstance(plan.publish.repository_id, int)
                or plan.publish.repository_id <= 0
                or not isinstance(plan.publish.installation_id, int)
                or plan.publish.installation_id <= 0
            ):
                raise ProjectOnboardError(
                    "The selected existing repository identity is incomplete; "
                    "check repositories again before Apply"
                )
            created = github_publish.verify_existing_repo(
                plan.publish.api_url,
                plan.publish.token,
                owner=plan.publish.owner,
                name=plan.publish.name,
                expected_head_sha=expected_head_sha,
                private=plan.publish.private,
                repository_id=plan.publish.repository_id,
                web_url=plan.publish.web_url,
            )
        elif origin_is(
            root, expected_origin, web_url=plan.publish.web_url,
        ):
            created = github_publish.verify_resumable_repo(
                plan.publish.api_url,
                plan.publish.token,
                owner=plan.publish.owner,
                name=plan.publish.name,
                private=plan.publish.private,
                expected_head_sha=expected_head_sha,
                web_url=plan.publish.web_url,
            )
        else:
            created = github_publish.create_repo(
                plan.publish.api_url,
                plan.publish.token,
                owner=plan.publish.owner,
                name=plan.publish.name,
                user_login=plan.publish.user_login,
                private=plan.publish.private,
                administration_allowed=plan.publish.administration_allowed,
                web_url=plan.publish.web_url,
            )
        new_origin_url = https_remote(
            created["full_name"], web_url=plan.publish.web_url,
        )
        origin_rehomed = origin_is(
            root, new_origin_url, web_url=plan.publish.web_url,
        )
        pushed_branch = rehome_to_new_origin(
            root,
            new_origin_url=new_origin_url,
            default_branch=default_branch,
            keep_upstream=plan.keep_upstream,
            token=plan.publish.token,
            github_web_url=plan.publish.web_url,
        )
        return CloneApplyResult(
            github_repo=created["full_name"],
            publication_read_only=False,
            branch=pushed_branch,
            clone_reused=clone_reused,
            repo_reused=bool(created.get("reused")),
            origin_rehomed=origin_rehomed,
        )
    if plan.outcome == CLONE_OUTCOME_FORK and plan.fallback_token:
        if not plan.fork_allowed:
            raise ProjectOnboardError(plan.fork_unavailable_reason or github_fork_access.UNVERIFIED)
        owner, repo = source_owner_repo(remote_url, web_url=plan.fork_web_url)
        existing_fork = project_clone_fork_resume.existing_fork_repo(
            root, remote_url=remote_url, web_url=plan.fork_web_url,
        ) if clone_reused else None
        fork = (
            github_publish.verify_resumable_fork(
                plan.fork_api_url,
                plan.fallback_token,
                source_owner=owner,
                source_repo=repo,
                candidate_full_name=existing_fork,
                web_url=plan.fork_web_url,
            )
            if existing_fork
            else github_publish.fork_repo(
                plan.fork_api_url, plan.fallback_token, owner=owner, repo=repo,
                web_url=plan.fork_web_url,
            )
        )
        set_fork_remotes(
            root,
            fork_url=https_remote(fork["full_name"], web_url=plan.fork_web_url),
            github_web_url=plan.fork_web_url,
        )
        return CloneApplyResult(
            github_repo=fork["full_name"],
            publication_read_only=False,
            branch=git_current_branch(root),
            clone_reused=clone_reused,
            repo_reused=bool(fork.get("reused")),
        )
    # The source remains available for fetches in both source outcomes.
    return CloneApplyResult(
        github_repo=None,
        publication_read_only=(plan.outcome == CLONE_OUTCOME_JUST_CLONE)
        if plan.outcome in (CLONE_OUTCOME_JUST_CLONE, CLONE_OUTCOME_SOURCE) else None,
        branch=git_current_branch(root),
        clone_reused=clone_reused,
    )


__all__ = [
    "CloneApplyResult",
    "apply_clone_outcome",
    "prepare_clone_plan",
    "machine_token_provider",
    "normalize_clone_request",
    "resumable_clone",
    "resumable_clone_with_machine_access",
]
