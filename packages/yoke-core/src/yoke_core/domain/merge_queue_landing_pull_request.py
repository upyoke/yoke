"""The one pull request a queued item branch lands through.

Two callers need the same pull request. The verification gate opens it, so
that the ``pull_request`` run GitHub mints for it is the run whose
conclusion becomes the case verdict
(:mod:`yoke_core.domain.qa_case_ci_entry_run`). The landing then converges
on whatever is already there
(:mod:`yoke_core.domain.merge_queue_route`) and enqueues it.

Both go through this function so the pull request the gate opened is the
pull request the landing enqueues, rather than a second one racing it.

Only one of them publishes the branch, though, and it is the gate. Item
branches stay local until something pushes them, so a landing whose
verification was satisfied any other way — a waived gate, a case that could
not run — arrives at a pull request for a branch GitHub has never seen, and
GitHub refuses that as a bare HTTP 422. The landing therefore owns its own
precondition: it publishes the branch when origin does not have it, whatever
satisfied verification.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from yoke_core.domain import standalone_item_merge_git as git
from yoke_core.engines.merge_worktree_pr_discovery import (
    find_landable_pull_request,
)
from yoke_core.engines.merge_worktree_pr_rest import (
    PrCreateResult,
    create_pr,
)
from yoke_core.engines.merge_worktree_prepare import MergeContext


def _publish_branch_if_absent(
    ctx: MergeContext, *, lane_head: str
) -> Optional[str]:
    """Put the branch on origin when it is not there yet.

    Publishing is the same ``--force-with-lease`` push the verification gate
    performs, reached from here so the landing does not depend on the gate
    having run. Returns why the branch could not be published, or ``None``
    when origin has it — including the ordinary case where it always did.
    """
    if not ctx.repo_root or git.remote_branch_exists(
        ctx.repo_root, ctx.args.branch
    ):
        return None
    from yoke_core.domain.qa_case_ci_lane import push_lane
    from yoke_core.domain.qa_case_execution import QaCaseExecutionError

    try:
        push_lane(
            Path(ctx.repo_root),
            ctx.args.branch,
            source_ref=lane_head or f"refs/heads/{ctx.args.branch}",
        )
    except QaCaseExecutionError as exc:
        return (
            f"branch {ctx.args.branch!r} is absent from origin and could not "
            f"be published: {exc}"
        )
    return None


def _create_failure(ctx: MergeContext, created: PrCreateResult) -> str:
    """Why the create failed, naming an absent branch when that is the cause.

    GitHub reports a pull request for a branch it does not have as an
    unexplained 422, which reads as a broken landing rather than a missing
    push. Naming the cause is what turns a second waived gate into a
    one-command repair instead of the same wall.
    """
    detail = created.error_detail or "pull request create failed"
    if ctx.repo_root and not git.remote_branch_exists(
        ctx.repo_root, ctx.args.branch
    ):
        return (
            f"{detail} — branch {ctx.args.branch!r} is not on origin, which is "
            "what GitHub refuses to open a pull request for. Publish it and "
            f"re-run the landing: git -C {ctx.repo_root} push "
            f"--force-with-lease origin refs/heads/{ctx.args.branch}"
        )
    return detail


def ensure_landing_pull_request(
    ctx: MergeContext, item_ref: str, *, lane_head: str = "",
) -> tuple[str, Optional[str]]:
    """Find the pull request this landing may use, or open one.

    The lookup deliberately sees merged and closed pull requests: a landing
    re-entered after the queue merged has to converge on the pull request
    that merged, and opening a second one for a branch with nothing left
    against the base is the refusal that convergence exists to prevent.
    GitHub answering that refusal anyway means a pull request exists that
    the listing did not show, so the lookup runs once more before failing.

    A merged pull request that does not cover ``lane_head`` is not this
    landing's, so the lookup declines it and a fresh one is opened for the
    commits that have not landed. That refusal survives the re-lookup below:
    finding the same stale pull request again means the fresh landing has no
    pull request of its own, which is a named failure rather than a silent
    convergence on the wrong merge commit.
    """
    _, pr_num, stale = find_landable_pull_request(ctx, lane_head=lane_head)
    if pr_num:
        return pr_num, None
    publish_error = _publish_branch_if_absent(ctx, lane_head=lane_head)
    if publish_error:
        return "", publish_error
    created = create_pr(
        ctx,
        title=f"{item_ref}: merge queue landing",
        body=(
            f"Item branch for {item_ref}; lands through the merge queue's "
            "merge_group integration gate."
        ),
    )
    if created.pr_num:
        return created.pr_num, None
    if created.already_exists or created.no_commits:
        _, pr_num, stale = find_landable_pull_request(ctx, lane_head=lane_head)
        if pr_num:
            return pr_num, None
    if stale:
        return "", (
            f"branch {ctx.args.branch!r} carries commits beyond the pull "
            f"request that merged it ({stale}); open a pull request for the "
            "new commits, or reset the lane to what already landed"
        )
    if created.no_commits:
        return "", (
            f"branch {ctx.args.branch!r} has no commits against "
            f"{ctx.args.target!r} and no pull request records it landing; "
            "confirm where the branch merged before re-running the landing"
        )
    return "", _create_failure(ctx, created)


__all__ = ["ensure_landing_pull_request"]
