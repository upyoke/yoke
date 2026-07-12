"""Resumable clone + post-clone remote choreography for project onboarding.

Split out of :mod:`project_onboard` to keep both modules under the line budget.
:func:`resumable_clone` is the idempotent clone step (skip an already-present
clone, error with recovery guidance on a genuine conflict);
:func:`apply_clone_outcome` runs the chosen post-clone remote choreography
(just-clone / make-it-mine / fork) and reports the repo, live branch, and which
steps were *reused* from a prior partial run rather than done fresh — so the
onboarding report can read differently after a resume.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Callable

from yoke_cli.config import github_local_user_access, github_publish, machine_config
from yoke_cli.config import onboard_wizard_github_state
from yoke_cli.config import project_clone_fork_resume
from yoke_cli.config.project_clone_resume import existing_clone_matches
from yoke_cli.config.project_clone_support import (
    CLONE_OUTCOME_FORK,
    CLONE_OUTCOME_MAKE_IT_MINE,
    ClonePlan,
    clone_with_token_fallback,
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
) -> ClonePlan:
    """Thread the configured App deployment and request-scoped user access."""
    github_config = machine_config.github_config(config_path)
    if github_config:
        plan = replace(
            plan,
            fork_web_url=str(github_config.get("web_url") or plan.fork_web_url),
            fork_allowed=(
                onboard_wizard_github_state.fork_ready_from_config(
                    github_config, remote_url,
                )
                if plan.outcome == CLONE_OUTCOME_FORK else plan.fork_allowed
            ),
        )
    if (
        plan.fallback_token is None
        and plan.use_machine_github
        and plan.outcome in (CLONE_OUTCOME_FORK, CLONE_OUTCOME_MAKE_IT_MINE)
    ):
        try:
            token = github_local_user_access.access_token(
                config_path=config_path,
            )
        except github_local_user_access.GitHubLocalUserAccessError as exc:
            raise ProjectOnboardError(
                "Connected GitHub App authorization could not be refreshed for "
                "the clone. Run `yoke github connect` again, or disconnect it "
                "before cloning a public repository."
            ) from exc
        plan = replace(plan, fallback_token=token.access_token)
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
) -> Callable[[], str | None] | None:
    """Return a lazy token source for an explicitly private clone."""
    if not plan.use_machine_github or plan.fallback_token:
        return None

    def provide() -> str:
        try:
            return github_local_user_access.access_token(
                config_path=config_path,
            ).access_token
        except github_local_user_access.GitHubLocalUserAccessError as exc:
            raise ProjectOnboardError(
                "Connected GitHub App authorization could not be refreshed "
                "after anonymous clone access failed. Reconnect GitHub and retry."
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


def resumable_clone(
    root: Path,
    remote_url: str,
    *,
    token: str | None,
    token_provider: Callable[[], str | None] | None = None,
    github_web_url: str | None = None,
) -> bool:
    """Clone ``remote_url`` into ``root``, skipping when it is already cloned.

    Resumable apply: a re-run after a partial onboarding may find the source
    already cloned into the target. When ``root`` is already a clone of
    ``remote_url`` (origin or upstream matches), the clone is skipped so the
    remaining steps resume. An empty / not-yet-existing target is cloned. A
    non-empty target that is NOT this source is a genuine conflict — raised with a
    recovery-shaped message naming the target and both ways forward.

    Returns ``True`` when an existing matching clone was reused (the clone was
    skipped), ``False`` when a fresh clone was made — so the caller can tell the
    user the clone was reused on a resume.
    """
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
    clone_with_token_fallback(
        root.parent, root.name, clean_remote,
        token=token, token_provider=token_provider,
        github_web_url=github_web_url,
    )
    return False


def resumable_clone_with_machine_fallback(
    root: Path,
    remote_url: str,
    *,
    plan: ClonePlan,
    config_path: str | Path | None,
    clone: Callable[..., bool] = resumable_clone,
) -> bool:
    """Run anonymous-first clone with a lazy machine token when requested."""

    return clone(
        root,
        remote_url,
        token=plan.fallback_token,
        token_provider=machine_token_provider(plan, config_path),
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
    """Run the post-clone remote choreography; return a :class:`CloneApplyResult`.

    ``CloneApplyResult.branch`` is the clone's live default branch, detected from
    the working copy rather than assumed — a clone of a `master` source records
    `master`, never a hardcoded `main`. ``make-it-mine`` re-homes onto a freshly
    created private repo and the branch is the one the re-home actually pushed;
    ``just-clone`` / ``fork`` leave the source / fork as ``origin`` and the
    branch is simply the checked-out one. Both repo-creating outcomes also record
    the created/forked ``owner/repo`` so the project is recorded against the repo
    the user now owns; ``just-clone`` records ``None`` for the repo (metadata
    keeps whatever github_repo the caller passed).

    The result also carries the resume flags so the report can read differently
    after a resumed run: ``clone_reused`` is threaded straight through from the
    clone step; ``repo_reused`` reflects ``make-it-mine`` adopting an existing
    empty repo on the 422 path; ``origin_rehomed`` records that ``origin`` was
    already pointing at the new repo so the remote re-home was skipped.
    """
    if plan.outcome == CLONE_OUTCOME_MAKE_IT_MINE and plan.publish is not None:
        expected_origin = https_remote(
            plan.publish.full_name, web_url=plan.publish.web_url,
        )
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
        # Probed BEFORE the re-home so we can tell whether the remote setup was a
        # no-op resume (origin already pointed at the new repo) or a fresh
        # re-home — rehome_to_new_origin uses the same predicate internally to
        # decide whether to skip the rename/add, then always (re-)pushes.
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
            branch=pushed_branch,
            clone_reused=clone_reused,
            repo_reused=bool(created.get("reused")),
            origin_rehomed=origin_rehomed,
        )
    if plan.outcome == CLONE_OUTCOME_FORK and plan.fallback_token:
        if not plan.fork_allowed:
            raise ProjectOnboardError(
                "Creating a fork through Yoke requires Administration: write, "
                "Contents access, all-repositories access on the destination, "
                "and source-repository access. The baseline Yoke GitHub App "
                "does not request Administration; clone the repository without "
                "forking, or create the fork in GitHub first."
            )
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
            branch=git_current_branch(root),
            clone_reused=clone_reused,
            repo_reused=bool(fork.get("reused")),
        )
    # just-clone (or fork without a token): origin stays the source; the recorded
    # default branch is still the clone's real checked-out branch.
    return CloneApplyResult(
        github_repo=None,
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
    "resumable_clone_with_machine_fallback",
]
