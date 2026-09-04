"""Queue landing with a durable handoff and no silent local fallback."""

from __future__ import annotations

import sys
import time
from typing import Any, Callable, Optional

from yoke_core.api.service_client_structured_api_adapter import call_dispatcher
from yoke_core.domain.github_poll_schedule import (
    PollSchedule,
    STEADY_SCHEDULE,
)
from yoke_core.domain.merge_queue_admission import evaluate_admission
from yoke_core.domain.merge_queue_admission_shape import (
    candidate_shape,
    train_context,
)
from yoke_core.domain.merge_queue_enqueue_verification import (
    red_entry_checks_refusal,
    verify_landing_admitted,
)
from yoke_core.domain.merge_queue_failed_train import (
    unchanged_failed_train_refusal,
)
from yoke_core.domain.merge_queue_landing_pull_request import (
    ensure_landing_pull_request,
)
from yoke_core.domain.merge_queue_landing_outcome import (
    QueueLandingOutcome,
    close_out,
    fail_landing,
    recorded_landing,
)
from yoke_core.domain.merge_queue_landing_pending import mark_landing_pending
from yoke_core.domain.merge_queue_landing_wait import (
    DEFAULT_DEADLINE_SECONDS,
    POLL_LINE_PREFIX,
    RECOVERABLE_QUEUE_EXIT_CODE,
    wait_for_queue_landing,
)
from yoke_core.domain.merge_queue_drift_gate import drift_check_before_landing
from yoke_core.domain.session_liveness_pump import SessionLivenessPump
from yoke_core.engines.merge_worktree_pr_queue import (
    enter_merge_queue,
    read_pr_landing_state,
    read_queue_members,
)
from yoke_core.engines.merge_worktree_prepare import MergeContext


def _emit_to_stderr(line: str) -> None:
    print(line, file=sys.stderr, flush=True)


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
    schedule: PollSchedule = STEADY_SCHEDULE,
    deadline_seconds: float = DEFAULT_DEADLINE_SECONDS,
    resume_command: str = "",
    liveness: Optional[SessionLivenessPump] = None,
    emit: Callable[[str], None] = _emit_to_stderr,
    wait_for_landing: bool = True,
) -> QueueLandingOutcome:
    """Land one verified item branch through the merge queue."""
    warnings: list[str] = []

    # A landing already recorded from GitHub leaves nothing to land, so the
    # queue is never consulted again: re-reading membership would find this
    # pull request gone and the admission gate would refuse a train that
    # already ran, turning the one recoverable state — merged, not closed
    # out — into a refusal. Close-out itself is idempotent bookkeeping.
    recorded_pr, recorded_landed_at = recorded_landing(dispatch, item_id)
    if recorded_pr and recorded_landed_at:
        emit(
            f"[phase:landing] pull request {recorded_pr} landed at "
            f"{recorded_landed_at}; closing out from the recorded landing"
        )
        return close_out(
            ctx,
            item_id=item_id,
            public_ref=public_ref,
            commit_sha=commit_sha,
            pr_num=recorded_pr,
            member_refs=(),
            drift=None,
            resume_command=resume_command,
            warnings=warnings,
        )

    # A comparison that could not run rides the batch evidence instead.
    drift = drift_check_before_landing(
        ctx.project or "",
        checkout=ctx.repo_root,
        branch=target,
        item_id=item_id,
    )
    if drift.drifted:
        return QueueLandingOutcome(
            ok=False, exit_code=1, error=drift.refusal(ctx.project or "")
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

    # The verification gate normally opened this pull request already.
    pr_num, pr_err = ensure_landing_pull_request(
        ctx,
        public_ref,
        lane_head=commit_sha,
        item_id=item_id,
    )
    if pr_err:
        return QueueLandingOutcome(ok=False, exit_code=1, error=pr_err)
    # GitHub refuses re-enabling an armed or already-merged pull request.
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
        # Arming a pull request its own required checks have already
        # refused is what turns a red gate into a wait nothing ends:
        # merge-when-ready takes, and every later read sees an armed
        # landing waiting for an entry GitHub will never create.
        red_checks = red_entry_checks_refusal(ctx, pr_num)
        if red_checks:
            return fail_landing(pr_num, red_checks, tuple(warnings))
        entry = enter_merge_queue(ctx, pr_num)
        if not entry.success:
            return QueueLandingOutcome(
                ok=False,
                exit_code=1,
                pr_num=pr_num,
                error=entry.error_detail or "queue entry refused",
            )

    # Arming is a request. What the handoff depends on is GitHub reporting
    # that it holds the landing, which the mutation's own success does not.
    if not already_merged:
        not_admitted = verify_landing_admitted(ctx, pr_num, target=target, sleep=sleep)
        if not_admitted:
            return fail_landing(
                pr_num,
                not_admitted,
                tuple(warnings),
                exit_code=RECOVERABLE_QUEUE_EXIT_CODE,
            )

    # Both landing routes hand the observation to the control plane. The
    # explicit waiter keeps its local process alive, but it reads this durable
    # record instead of issuing its own GitHub polls.
    if not already_merged:
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
                    f"its durable landing marker was not recorded: {marker_error}. "
                    "Repair the control-plane write and re-enter `yoke merge item`; "
                    "the retry converges if GitHub landed it meanwhile."
                ),
                warnings=tuple(warnings),
            )
    else:
        enqueued_at = ""

    if not already_merged and not wait_for_landing:
        emit(
            f"[phase:landing] pull request {pr_num} is in the merge queue; "
            "this command is exiting with landing_pending=true. Re-enter on "
            "a completion message only when the watcher selected a verified "
            "background-wake route; otherwise run the same merge through "
            "the reachability-routed watcher with --wait"
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

    # Explicit wait mode keeps the owning session alive through the record wait.
    refusal = wait_for_queue_landing(
        pr_num=pr_num,
        target=target,
        item_id=item_id,
        public_ref=public_ref,
        resume_command=resume_command,
        dispatch=dispatch,
        sleep=sleep,
        monotonic=monotonic,
        schedule=schedule,
        deadline_seconds=deadline_seconds,
        liveness=liveness,
        emit=emit,
    )
    if refusal is not None:
        return fail_landing(
            pr_num,
            refusal.error,
            tuple(warnings),
            exit_code=refusal.exit_code,
        )

    return close_out(
        ctx,
        item_id=item_id,
        public_ref=public_ref,
        commit_sha=commit_sha,
        pr_num=pr_num,
        member_refs=member_refs,
        drift=drift,
        resume_command=resume_command,
        warnings=warnings,
        already_merged=already_merged,
    )


__all__ = [
    "DEFAULT_DEADLINE_SECONDS",
    "POLL_LINE_PREFIX",
    "RECOVERABLE_QUEUE_EXIT_CODE",
    "QueueLandingOutcome",
    "land_item_through_merge_queue",
]
