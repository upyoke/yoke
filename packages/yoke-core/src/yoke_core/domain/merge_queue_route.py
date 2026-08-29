"""Queue-routed landing for a verified item branch.
Admission and PR arming are re-enterable: default mode records a durable
handoff, while explicit wait mode polls the train. Both converge on an already
merged PR and the same receipt; failures never silently downgrade to local merge.
"""

from __future__ import annotations

import sys
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from yoke_core.api.service_client_structured_api_adapter import call_dispatcher
from yoke_core.domain.github_poll_schedule import (
    CI_SUITE_SCHEDULE,
    PollSchedule,
    next_read_delay,
)
from yoke_core.domain.merge_queue_admission import evaluate_admission
from yoke_core.domain.merge_queue_admission_shape import (
    candidate_shape,
    train_context,
)
from yoke_core.domain.merge_queue_batch_receipt import BatchReceipt
from yoke_core.domain.merge_queue_close_out import record_landing
from yoke_core.domain.merge_queue_failed_train import (
    unchanged_failed_train_refusal,
)
from yoke_core.domain.merge_queue_landing_pull_request import (
    ensure_landing_pull_request,
)
from yoke_core.domain.merge_queue_landing_pending import mark_landing_pending
from yoke_core.domain.merge_queue_landing_timeout import timeout_message
from yoke_core.domain.merge_queue_drift_gate import drift_check_before_landing
from yoke_core.domain.merge_queue_landing_verdict import (
    CLOSED_UNMERGED,
    CONFLICTED,
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

DEFAULT_DEADLINE_SECONDS = 45.0 * 60.0

# Every poll observation is announced under this prefix. The wait is the
# landing's longest step by far, and a pull request the queue never took up
# reads exactly like one mid-train unless each observation says what it saw;
# the watcher wrapper classifies these lines as progress by this prefix.
POLL_LINE_PREFIX = "Queue landing:"


def _emit_to_stderr(line: str) -> None:
    """Announce one poll observation without disturbing stdout.

    The caller's result envelope is stdout's; progress belongs on stderr,
    where the merge watcher already reads it.
    """
    print(line, file=sys.stderr, flush=True)


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
    landing_pending: bool = False
    enqueued_at: str = ""
    error: str = ""
    warnings: tuple[str, ...] = field(default=())


def land_item_through_merge_queue(
    ctx: MergeContext,
    *,
    item_id: int,
    public_ref: str,
    commit_sha: str,
    target: str = "main",
    dispatch: Callable[..., Any] = call_dispatcher,
    sleep: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
    schedule: PollSchedule = CI_SUITE_SCHEDULE,
    deadline_seconds: float = DEFAULT_DEADLINE_SECONDS,
    resume_command: str = "",
    liveness: Optional[SessionLivenessPump] = None,
    emit: Callable[[str], None] = _emit_to_stderr,
    wait_for_landing: bool = True,
) -> QueueLandingOutcome:
    """Land one verified item branch through the merge queue."""
    warnings: list[str] = []

    # The queue enforces whatever the live ruleset requires, so landing
    # into a drifted one is gated on a set main already disowned.
    drift = drift_check_before_landing(
        ctx.project or "",
        checkout=ctx.repo_root,
        branch=target,
        item_id=item_id,
    )
    if drift.drifted:
        return QueueLandingOutcome(
            ok=False,
            exit_code=1,
            error=drift.refusal(ctx.project or ""),
        )
    warnings.extend(drift.unreadable)

    members, members_err = read_queue_members(ctx, base_branch=target)
    if members_err or members is None:
        return QueueLandingOutcome(
            ok=False, exit_code=1, error=members_err or "queue unreadable"
        )
    member_refs = tuple(
        member.head_ref
        for member in members
        if member.head_ref and member.head_ref != ctx.args.branch
    )

    candidate, candidate_err = candidate_shape(dispatch, public_ref)
    if candidate_err:
        return QueueLandingOutcome(ok=False, exit_code=1, error=candidate_err)
    context, context_err = train_context(dispatch, public_ref, member_refs, ctx.project)
    if context_err:
        return QueueLandingOutcome(ok=False, exit_code=1, error=context_err)
    warnings.extend(context.notes)
    verdict = evaluate_admission(candidate, context)
    if not verdict.admit:
        return QueueLandingOutcome(
            ok=False,
            exit_code=RECOVERABLE_QUEUE_EXIT_CODE,
            error=verdict.narrative(),
            warnings=tuple(warnings),
        )

    # The verification gate already opened this pull request for a project
    # routed through the queue, so this call normally converges on it.
    pr_num, pr_err = ensure_landing_pull_request(
        ctx,
        public_ref,
        lane_head=commit_sha,
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
        refusal = unchanged_failed_train_refusal(
            ctx,
            pr_num,
            lane_head=commit_sha,
            base_branch=target,
        )
        if refusal:
            return QueueLandingOutcome(
                ok=False,
                exit_code=1,
                pr_num=pr_num,
                error=refusal,
                warnings=tuple(warnings),
            )
        entry = enter_merge_queue(ctx, pr_num)
        if not entry.success:
            return QueueLandingOutcome(
                ok=False,
                exit_code=1,
                pr_num=pr_num,
                error=entry.error_detail or "queue entry refused",
            )

    if not already_merged and not wait_for_landing:
        enqueued_at, marker_error = mark_landing_pending(
            item_id,
            pr_num,
            dispatch=dispatch,
        )
        if marker_error:
            return QueueLandingOutcome(
                ok=False,
                exit_code=1,
                pr_num=pr_num,
                error=(
                    f"pull request {pr_num} is armed in the merge queue, but "
                    f"its durable close-out marker was not recorded: {marker_error}. "
                    "Re-enter with --wait to converge on the landing."
                ),
                warnings=tuple(warnings),
            )
        emit(
            f"[phase:landing] pull request {pr_num} is in the merge queue; "
            "this command is exiting until the landing-complete notification"
        )
        return QueueLandingOutcome(
            ok=True,
            exit_code=0,
            pr_num=pr_num,
            commit_sha=commit_sha,
            landing_pending=True,
            enqueued_at=enqueued_at,
            warnings=tuple(warnings),
        )

    # Explicit wait mode keeps the owning session alive through the poll.
    started = monotonic()
    deadline = started + deadline_seconds
    pump = liveness if liveness is not None else SessionLivenessPump()
    merged = False
    last_seen = ""
    last_announced = ""
    now = started
    while now < deadline:
        pump.tick()
        landing = classify_landing(
            ctx,
            pr_num=pr_num,
            target=target,
            sleep=sleep,
        )
        warnings.extend(landing.warnings)
        if landing.narrative:
            last_seen = landing.narrative
            if landing.narrative != last_announced:
                last_announced = landing.narrative
                emit(
                    f"{POLL_LINE_PREFIX} {landing.narrative} "
                    f"(elapsed: {int(now - started)}s)"
                )
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
        if landing.kind == CONFLICTED:
            return QueueLandingOutcome(
                ok=False,
                exit_code=RECOVERABLE_QUEUE_EXIT_CODE,
                pr_num=pr_num,
                error=(
                    f"pull request {pr_num} has merge conflicts — observed "
                    f"{landing.narrative}; rebase onto the current base and "
                    "re-enter the queue"
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
        pump.wait(next_read_delay(now - started, schedule), sleep=sleep)
        now = monotonic()
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
                public_ref=public_ref,
                resume_command=resume_command,
                dispatch=dispatch,
                last_observed=last_seen,
            ),
            warnings=tuple(warnings),
        )

    close_out = record_landing(
        ctx,
        item_id=item_id,
        commit_sha=commit_sha,
        pr_num=pr_num,
        member_snapshot=tuple(dict.fromkeys((*member_refs, public_ref))),
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
    "POLL_LINE_PREFIX",
    "RECOVERABLE_QUEUE_EXIT_CODE",
    "QueueLandingOutcome",
    "land_item_through_merge_queue",
]
