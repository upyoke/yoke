"""Queue-routed landing for a verified item branch.

The standalone engine merges locally under the merge lock; this route
lands the same branch through the GitHub merge queue instead: admission
control against current queue membership, PR ensure + merge-when-ready
entry, a poll on the PR's merged state while the queue validates the
train's combined head server-side, then the member's close-out — the
``merged_at`` stamp and the batch verification receipt. Lifecycle status
and GitHub sync stay caller-owned, exactly as they are for the
standalone engine, so both routes drive the same downstream gates.

Every step is re-enterable against a landing that already happened,
because the queue merges on GitHub whether or not the process watching it
survives: the pull request is looked up in any state, queue entry is
skipped for one already merged or already armed, and a poll only ever
converges on the pull request's own terminal state
(:mod:`yoke_core.domain.merge_queue_landing_verdict`). A retry after the
queue merged reaches the same close-out the first attempt would have.

No lock wraps any of this: the expensive gate runs inside GitHub, and
the Yoke-side close-out is one short bookkeeping step per member.
Every refusal is named — an unreachable or unconfigured queue is an
error the caller surfaces, never a silent downgrade to a local merge.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from yoke_core.api.service_client_structured_api_adapter import call_dispatcher
from yoke_core.domain.merge_queue_admission import evaluate_admission
from yoke_core.domain.merge_queue_admission_shape import (
    candidate_shape,
    train_context,
)
from yoke_core.domain.merge_queue_batch_receipt import BatchReceipt
from yoke_core.domain.merge_queue_close_out import record_landing
from yoke_core.domain.merge_queue_landing_verdict import (
    CLOSED_UNMERGED,
    LANDED,
    STALLED,
    classify_landing,
)
from yoke_core.engines.merge_worktree_pr_discovery import (
    find_branch_pull_request,
)
from yoke_core.engines.merge_worktree_pr_queue import (
    enter_merge_queue,
    read_pr_landing_state,
    read_queue_members,
)
from yoke_core.engines.merge_worktree_pr_rest import create_pr
from yoke_core.engines.merge_worktree_prepare import MergeContext


# Admission refusals and a queue that has stopped driving a pull request are
# retry-later outcomes, the same recoverable class as the standalone engine's
# held merge lock (exit 6). Exit 9 is free at the done-transition boundary,
# whose codes 0-4, 7 (deployment flow guard), 8 (empty branch), and 99 are
# taken.
RECOVERABLE_QUEUE_EXIT_CODE = 9

DEFAULT_POLL_SECONDS = 30.0
DEFAULT_DEADLINE_SECONDS = 45.0 * 60.0


@dataclass(frozen=True)
class QueueLandingOutcome:
    """What one queue-routed landing attempt produced."""

    ok: bool
    exit_code: int
    pr_num: str = ""
    commit_sha: str = ""
    merge_sha: str = ""
    touched_files: tuple[str, ...] = field(default=())
    batch: Optional[BatchReceipt] = None
    already_merged: bool = False
    error: str = ""
    warnings: tuple[str, ...] = field(default=())


def _ensure_pr(ctx: MergeContext, item_ref: str) -> tuple[str, Optional[str]]:
    """Find the branch's pull request in any state, or open one.

    The lookup deliberately sees merged and closed pull requests: a landing
    re-entered after the queue merged has to converge on the pull request
    that merged, and opening a second one for a branch with nothing left
    against the base is the refusal that convergence exists to prevent.
    GitHub answering that refusal anyway means a pull request exists that
    the listing did not show, so the lookup runs once more before failing.
    """
    _, pr_num = find_branch_pull_request(ctx)
    if pr_num:
        return pr_num, None
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
        _, pr_num = find_branch_pull_request(ctx)
        if pr_num:
            return pr_num, None
    if created.no_commits:
        return "", (
            f"branch {ctx.args.branch!r} has no commits against "
            f"{ctx.args.target!r} and no pull request records it landing; "
            "confirm where the branch merged before re-running the landing"
        )
    return "", created.error_detail or "pull request create failed"


def land_item_through_merge_queue(
    ctx: MergeContext,
    *,
    item_id: int,
    item_ref: str,
    commit_sha: str,
    target: str = "main",
    dispatch: Callable[..., Any] = call_dispatcher,
    sleep: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
    poll_seconds: float = DEFAULT_POLL_SECONDS,
    deadline_seconds: float = DEFAULT_DEADLINE_SECONDS,
) -> QueueLandingOutcome:
    """Land one verified item branch through the merge queue."""
    warnings: list[str] = []

    members, members_err = read_queue_members(ctx, base_branch=target)
    if members_err or members is None:
        return QueueLandingOutcome(
            ok=False, exit_code=1, error=members_err or "queue unreadable"
        )
    member_refs = tuple(
        member.head_ref for member in members
        if member.head_ref and member.head_ref != ctx.args.branch
    )

    candidate, candidate_err = candidate_shape(dispatch, item_ref)
    if candidate_err:
        return QueueLandingOutcome(
            ok=False, exit_code=1, error=candidate_err
        )
    context, context_err = train_context(dispatch, item_ref, member_refs)
    if context_err:
        return QueueLandingOutcome(ok=False, exit_code=1, error=context_err)
    verdict = evaluate_admission(candidate, context)
    if not verdict.admit:
        return QueueLandingOutcome(
            ok=False,
            exit_code=RECOVERABLE_QUEUE_EXIT_CODE,
            error=verdict.narrative(),
        )

    pr_num, pr_err = _ensure_pr(ctx, item_ref)
    if pr_err:
        return QueueLandingOutcome(ok=False, exit_code=1, error=pr_err)
    # Convergent re-entry: skip queue entry when the PR already merged or
    # is already armed — GitHub refuses re-enabling merge-when-ready.
    pre_state, pre_err = read_pr_landing_state(ctx, pr_num)
    if pre_err:
        warnings.append(pre_err)
    already_merged = bool(pre_state is not None and pre_state.merged)
    already_armed = bool(
        pre_state is not None
        and not pre_state.merged
        and not pre_state.closed
        and pre_state.auto_merge_active
    )
    if pre_state is None or not (already_merged or already_armed):
        entry = enter_merge_queue(ctx, pr_num)
        if not entry.success:
            return QueueLandingOutcome(
                ok=False,
                exit_code=1,
                pr_num=pr_num,
                error=entry.error_detail or "queue entry refused",
            )

    deadline = monotonic() + deadline_seconds
    merged = False
    while monotonic() < deadline:
        landing = classify_landing(
            ctx, pr_num=pr_num, target=target, sleep=sleep,
        )
        warnings.extend(landing.warnings)
        if landing.kind == LANDED:
            merged = True
            break
        if landing.kind == CLOSED_UNMERGED:
            return QueueLandingOutcome(
                ok=False,
                exit_code=1,
                pr_num=pr_num,
                error=(
                    f"pull request {pr_num} closed without merging — observed "
                    f"{landing.narrative}; reopen or recreate it before "
                    "re-entering the queue"
                ),
                warnings=tuple(warnings),
            )
        if landing.kind == STALLED:
            return QueueLandingOutcome(
                ok=False,
                exit_code=RECOVERABLE_QUEUE_EXIT_CODE,
                pr_num=pr_num,
                error=(
                    f"the merge queue is no longer driving pull request "
                    f"{pr_num} — observed {landing.narrative}; address what "
                    "the train run reports and re-enter the queue. Re-running "
                    "the landing is safe: it converges on the merge if one "
                    "happens meanwhile"
                ),
                warnings=tuple(warnings),
            )
        sleep(poll_seconds)
    if not merged:
        return QueueLandingOutcome(
            ok=False,
            exit_code=RECOVERABLE_QUEUE_EXIT_CODE,
            pr_num=pr_num,
            error=(
                f"pull request {pr_num} did not merge within "
                f"{int(deadline_seconds)}s; inspect the queue position and "
                "train checks, then re-run the landing to resume polling"
            ),
            warnings=tuple(warnings),
        )

    close_out = record_landing(
        ctx,
        item_id=item_id,
        commit_sha=commit_sha,
        pr_num=pr_num,
        member_snapshot=tuple(dict.fromkeys((*member_refs, item_ref))),
    )
    warnings.extend(close_out.warnings)
    return QueueLandingOutcome(
        ok=True,
        exit_code=0,
        pr_num=pr_num,
        commit_sha=commit_sha,
        merge_sha=close_out.merge_sha,
        touched_files=close_out.touched_files,
        batch=close_out.batch,
        already_merged=already_merged,
        warnings=tuple(warnings),
    )


__all__ = [
    "DEFAULT_DEADLINE_SECONDS",
    "DEFAULT_POLL_SECONDS",
    "RECOVERABLE_QUEUE_EXIT_CODE",
    "QueueLandingOutcome",
    "land_item_through_merge_queue",
]
