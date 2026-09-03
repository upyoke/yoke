"""The one pull request a queued item branch lands through.

Two callers need the same pull request. The verification gate opens it, so
that the ``pull_request`` run GitHub mints for it is the run whose
conclusion becomes the case verdict
(:mod:`yoke_core.domain.qa_case_ci_entry_run`). The landing then converges
on whatever is already there
(:mod:`yoke_core.domain.merge_queue_route`) and enqueues it.

Both go through this function so the pull request the gate opened is the
pull request the landing enqueues, rather than a second one racing it.

The gate is the usual publisher, but the landing owns the precondition that
origin holds the reported ``lane_head``. Item branches stay local until
something pushes them, so a landing whose verification was satisfied any
other way — a waived gate, a case that could not run — arrives at a pull
request for a branch GitHub has never seen, and GitHub refuses that as a
bare HTTP 422. A retry after a red train is the same gap with a twist:
origin already has the branch, just not the new commits, and reporting
``ok`` with the new SHA while the queue stays armed on the old one is a
silent divergence. The landing therefore publishes ``lane_head`` whenever
origin does not already hold it.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from yoke_contracts.github_app_installation_permissions import (
    GITHUB_PULL_REQUESTS_WRITE_PERMISSION_LEVELS as PR_WRITE,
)
from yoke_core.domain import standalone_item_merge_git as git
from yoke_core.domain.gh_rest_transport import (
    RestRequest,
    RestTransportError,
    request_with_retry,
    split_repo,
)
from yoke_core.engines.merge_worktree_pr_discovery import (
    find_landable_pull_request,
)
from yoke_core.engines.merge_worktree_pr_queue import read_pr_landing_state
from yoke_core.engines.merge_worktree_pr_rest import (
    AuthResolutionFailed,
    PrCreateResult,
    create_pr,
    resolve_auth,
)
from yoke_core.engines.merge_worktree_prepare import MergeContext


def _same_commit(left: str, right: str) -> bool:
    a, b = left.strip().lower(), right.strip().lower()
    return bool(a) and a == b


def _publish_recovery(ctx: MergeContext, *, lane_head: str) -> str:
    source = lane_head or f"refs/heads/{ctx.args.branch}"
    root = ctx.repo_root or "."
    return (
        f"git -C {root} push --force-with-lease origin "
        f"{source}:refs/heads/{ctx.args.branch}"
    )


def _publish_lane_head(ctx: MergeContext, *, lane_head: str) -> Optional[str]:
    """Put ``lane_head`` on origin under the lane branch.

    Publishing is the same ``--force-with-lease`` push the verification gate
    performs, reached from here so the landing does not depend on the gate
    having run and so a retry cannot report a SHA origin does not hold.
    Returns why the head could not be published, or ``None`` when origin
    already has it — including the ordinary case where the gate just did.
    """
    if not ctx.repo_root:
        return None
    remote_sha = git.remote_head_of(ctx.repo_root, ctx.args.branch)
    if lane_head:
        already_published = _same_commit(remote_sha, lane_head)
    else:
        already_published = bool(remote_sha)
    if already_published:
        return None
    from yoke_core.domain.qa_case_ci_lane import push_lane
    from yoke_core.domain.qa_case_execution import QaCaseExecutionError

    source = lane_head or f"refs/heads/{ctx.args.branch}"
    try:
        push_lane(
            Path(ctx.repo_root),
            ctx.args.branch,
            source_ref=source,
        )
    except QaCaseExecutionError as exc:
        if not remote_sha:
            return (
                f"branch {ctx.args.branch!r} is absent from origin and could "
                f"not be published: {exc}"
            )
        return (
            f"lane head {source} is not what origin holds for "
            f"{ctx.args.branch!r} (remote head {remote_sha}); the queue is "
            f"landing the remote head, not the unpublished local commits. "
            f"Publishing failed: {exc}. Publish the lane head and re-run: "
            f"{_publish_recovery(ctx, lane_head=lane_head)}"
        )
    return None


def _open_pr_at_lane_head(
    ctx: MergeContext, pr_num: str, *, lane_head: str
) -> tuple[str, Optional[str]]:
    error = _publish_lane_head(ctx, lane_head=lane_head)
    if error:
        return "", error
    return pr_num, None


def _create_failure(ctx: MergeContext, created: PrCreateResult) -> str:
    """Why the create failed, naming an absent branch when that is the cause.

    GitHub reports a pull request for a branch it does not have as an
    unexplained 422, which reads as a broken landing rather than a missing
    push. Naming the cause is what turns a second waived gate into a
    one-command repair instead of the same wall.
    """
    detail = created.error_detail or "pull request create failed"
    if ctx.repo_root and not git.remote_branch_exists(ctx.repo_root, ctx.args.branch):
        return (
            f"{detail} — branch {ctx.args.branch!r} is not on origin, which is "
            "what GitHub refuses to open a pull request for. Publish it and "
            f"re-run the landing: git -C {ctx.repo_root} push "
            f"--force-with-lease origin refs/heads/{ctx.args.branch}"
        )
    return detail


def reopen_pull_request(
    ctx: MergeContext,
    pr_num: str,
) -> tuple[str, Optional[str]]:
    """Reopen a closed pull request. Returns ``(pr_num, None)`` on success."""
    try:
        auth = resolve_auth(ctx, required_permissions=PR_WRITE)
    except AuthResolutionFailed as exc:
        return "", f"could not reopen pull request {pr_num}: {exc}"
    owner, repo = split_repo(auth.repo)
    try:
        response = request_with_retry(
            RestRequest(
                method="PATCH",
                path=f"/repos/{owner}/{repo}/pulls/{pr_num}",
                body={"state": "open"},
            ),
            token=auth.token,
        )
    except RestTransportError as exc:
        return "", f"could not reopen pull request {pr_num}: {exc}"
    body = response.body if isinstance(response.body, dict) else {}
    if str(body.get("state") or "") != "open":
        return "", (
            f"could not reopen pull request {pr_num}: state={body.get('state')!r}"
        )
    return pr_num, None


def _usable_existing_pull_request(
    ctx: MergeContext,
    pr_num: str,
) -> tuple[str, Optional[str], bool]:
    """Return ``(pr_num, None, merged)`` when the PR can be used."""
    state, _error = read_pr_landing_state(ctx, pr_num)
    if state is not None and (state.merged or not state.closed):
        return pr_num, None, bool(state.merged)
    reopened, reopen_error = reopen_pull_request(ctx, pr_num)
    if reopened:
        return reopened, None, False
    return "", reopen_error, False


def ensure_landing_pull_request(
    ctx: MergeContext,
    public_ref: str,
    *,
    lane_head: str = "",
    item_id: int = 0,
) -> tuple[str, Optional[str]]:
    """Resolve this landing's pull request and record it on the item.

    Recording here rather than at either caller is what makes the number
    survive a process that dies waiting: both the verification gate and the
    landing converge on this one function, so this is the only place that
    sees every pull request an item lands through. Recording is advisory —
    a landing that is otherwise fine does not fail because the marker write
    did — and ``item_id=0`` skips it for callers with no item in hand.
    """
    pr_num, error = _resolve_landing_pull_request(
        ctx,
        public_ref,
        lane_head=lane_head,
    )
    if pr_num and item_id:
        from yoke_core.domain.merge_queue_landing_pending import (
            record_landing_pull_request,
        )

        record_landing_pull_request(int(item_id), pr_num)
    return pr_num, error


def _resolve_landing_pull_request(
    ctx: MergeContext,
    public_ref: str,
    *,
    lane_head: str = "",
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

    A closed unmerged pull request is reopened when GitHub permits, and
    replaced by a new one when it does not. The adapter refuses only when
    neither path can produce an open pull request.

    An open pull request is reused only after origin holds ``lane_head``.
    A merged pull request is left unpublished: those commits already
    landed.
    """
    _, pr_num, stale = find_landable_pull_request(ctx, lane_head=lane_head)
    reopen_error = None
    if pr_num:
        usable, reopen_error, merged = _usable_existing_pull_request(ctx, pr_num)
        if usable:
            if merged:
                return usable, None
            return _open_pr_at_lane_head(ctx, usable, lane_head=lane_head)
    publish_error = _publish_lane_head(ctx, lane_head=lane_head)
    if publish_error:
        return "", publish_error
    created = create_pr(
        ctx,
        title=f"{public_ref}: merge queue landing",
        body=(
            f"Item branch for {public_ref}; lands through the merge queue's "
            "merge_group integration gate."
        ),
    )
    if created.pr_num:
        return created.pr_num, None
    if created.already_exists or created.no_commits:
        _, pr_num, stale = find_landable_pull_request(ctx, lane_head=lane_head)
        if pr_num:
            usable, _ignored, _merged = _usable_existing_pull_request(ctx, pr_num)
            if usable:
                return usable, None
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
    create_error = _create_failure(ctx, created)
    if reopen_error:
        return "", (
            f"closed unmerged pull request could not be reopened "
            f"({reopen_error}) and a replacement could not be created "
            f"({create_error})"
        )
    return "", create_error


__all__ = ["ensure_landing_pull_request", "reopen_pull_request"]
