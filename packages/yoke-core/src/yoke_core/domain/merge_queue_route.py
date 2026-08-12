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

Convergence is bounded by what actually merged. A lane that committed again
after its pull request merged still matches that pull request by branch name,
so the landing converges only on a merged pull request covering the lane head
and opens a fresh one otherwise — binding new commits to an old merge commit
would record evidence for work that never landed.

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
from yoke_core.domain.merge_queue_landing_pull_request import (
    ensure_landing_pull_request,
)
from yoke_core.domain.merge_queue_landing_timeout import timeout_message
from yoke_core.domain.merge_queue_landing_verdict import (
    CLOSED_UNMERGED,
    LANDED,
    STALLED,
    classify_landing,
)
from yoke_core.domain.session_liveness_pump import SessionLivenessPump
from yoke_core.engines.merge_worktree_pr_queue import (
    enter_merge_queue,
    read_pr_landing_state,
    read_queue_members,
)
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
    resume_command: str = "",
    liveness: Optional[SessionLivenessPump] = None,
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

    # The verification gate already opened this pull request for a project
    # routed through the queue, so this call normally converges on it.
    pr_num, pr_err = ensure_landing_pull_request(
        ctx, item_ref, lane_head=commit_sha,
    )
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

    # Waiting on the queue is work, but it is silent work: nothing this
    # loop does reaches the session's activity signals, so the stale sweep
    # would reclaim the session mid-poll and release the item claim the
    # close-out below — and any retry — depends on. The pump says the
    # session is still here for exactly as long as this process waits.
    deadline = monotonic() + deadline_seconds
    pump = liveness if liveness is not None else SessionLivenessPump()
    merged = False
    while monotonic() < deadline:
        pump.tick()
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
        # A poll-budget timeout is resumable, not terminal: the claim is
        # still held, so the message reports that and prints the command
        # that runs from there without an undocumented re-acquire.
        return QueueLandingOutcome(
            ok=False,
            exit_code=RECOVERABLE_QUEUE_EXIT_CODE,
            pr_num=pr_num,
            error=timeout_message(
                pr_num=pr_num,
                deadline_seconds=deadline_seconds,
                item_id=item_id,
                item_ref=item_ref,
                resume_command=resume_command,
                dispatch=dispatch,
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
