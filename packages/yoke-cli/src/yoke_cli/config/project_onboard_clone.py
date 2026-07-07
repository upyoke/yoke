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

from dataclasses import dataclass
from pathlib import Path

from yoke_cli.config import github_publish
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
from yoke_cli.config.project_git_transport import git_current_branch, https_remote
from yoke_cli.config.project_onboard_support import (
    ProjectOnboardError,
    ensure_new_checkout,
)


@dataclass(frozen=True)
class CloneApplyResult:
    """What the clone apply did, including which steps were reused on a resume.

    ``github_repo`` / ``branch`` are the recorded repo + live default branch (see
    :func:`apply_clone_outcome`). The three resume flags let the report
    distinguish a fresh run from one that picked up a prior partial run's work:

    * ``clone_reused`` — the working copy was already a clone of the source, so
      the clone step was skipped.
    * ``repo_reused`` — ``make-it-mine`` found its target repo already existing
      (empty, from a prior run) and adopted it instead of creating it.
    * ``origin_rehomed`` — ``make-it-mine`` found ``origin`` already pointing at
      the new repo, so the remote re-home was skipped (the push still ran).

    All three default ``False`` on a fresh run, so a first run reports exactly as
    before; only a resumed run flips them.
    """

    github_repo: str | None
    branch: str | None
    clone_reused: bool = False
    repo_reused: bool = False
    origin_rehomed: bool = False


def resumable_clone(root: Path, remote_url: str, *, token: str | None) -> bool:
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
    if existing_clone_matches(root, remote_url):
        return True
    if root.exists() and any(root.iterdir()):
        raise ProjectOnboardError(
            f"{root} already has files but isn't a clone of this repo. Re-run "
            "and pick an empty folder to resume cleanly, or remove "
            f"{root} to start over."
        )
    ensure_new_checkout(root)
    clone_with_token_fallback(root.parent, root.name, remote_url, token=token)
    return False


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
        created = github_publish.create_repo(
            plan.publish.api_url,
            plan.publish.token,
            owner=plan.publish.owner,
            name=plan.publish.name,
            user_login=plan.publish.user_login,
            private=plan.publish.private,
        )
        new_origin_url = https_remote(created["full_name"])
        # Probed BEFORE the re-home so we can tell whether the remote setup was a
        # no-op resume (origin already pointed at the new repo) or a fresh
        # re-home — rehome_to_new_origin uses the same predicate internally to
        # decide whether to skip the rename/add, then always (re-)pushes.
        origin_rehomed = origin_is(root, new_origin_url)
        pushed_branch = rehome_to_new_origin(
            root,
            new_origin_url=new_origin_url,
            default_branch=default_branch,
            keep_upstream=plan.keep_upstream,
            token=plan.publish.token,
        )
        return CloneApplyResult(
            github_repo=created["full_name"],
            branch=pushed_branch,
            clone_reused=clone_reused,
            repo_reused=bool(created.get("reused")),
            origin_rehomed=origin_rehomed,
        )
    if plan.outcome == CLONE_OUTCOME_FORK and plan.fallback_token:
        owner, repo = source_owner_repo(remote_url)
        fork = github_publish.fork_repo(
            plan.fork_api_url, plan.fallback_token, owner=owner, repo=repo,
        )
        set_fork_remotes(root, fork_url=https_remote(fork["full_name"]))
        return CloneApplyResult(
            github_repo=fork["full_name"],
            branch=git_current_branch(root),
            clone_reused=clone_reused,
        )
    # just-clone (or fork without a token): origin stays the source; the recorded
    # default branch is still the clone's real checked-out branch.
    return CloneApplyResult(
        github_repo=None,
        branch=git_current_branch(root),
        clone_reused=clone_reused,
    )


__all__ = ["CloneApplyResult", "apply_clone_outcome", "resumable_clone"]
