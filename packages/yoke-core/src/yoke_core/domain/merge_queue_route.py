"""Queue landing with a durable handoff and no silent local fallback."""

from __future__ import annotations

import sys
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from yoke_core.api.service_client_structured_api_adapter import call_dispatcher
from yoke_core.domain.github_poll_schedule import (
    CI_SUITE_SCHEDULE,
    PollSchedule,
)
from yoke_core.domain.merge_queue_admission import evaluate_admission
from yoke_core.domain.merge_queue_admission_shape import (
    candidate_shape,
    train_context,
)
from yoke_core.domain.merge_queue_batch_receipt import BatchReceipt
from yoke_core.domain.merge_queue_close_out import record_landing
from yoke_core.domain.merge_queue_enqueue_verification import (
    verify_landing_admitted,
)
from yoke_core.domain.merge_queue_failed_train import (
    unchanged_failed_train_refusal,
)
from yoke_core.domain.merge_queue_landing_pull_request import (
    ensure_landing_pull_request,
)
from yoke_core.domain.merge_queue_landing_pending import mark_landing_pending
from yoke_core.domain.merge_queue_landing_wait import (
    DEFAULT_DEADLINE_SECONDS,
    POLL_LINE_PREFIX,
    RECOVERABLE_QUEUE_EXIT_CODE,
    wait_for_queue_landing,
)
from yoke_core.domain.merge_queue_drift_gate import (
    drift_check_before_landing,
    drift_receipt,
)
from yoke_core.domain.session_liveness_pump import SessionLivenessPump
from yoke_core.engines.merge_worktree_pr_queue import (
    enter_merge_queue,
    read_pr_landing_state,
    read_queue_members,
)
from yoke_core.engines.merge_worktree_prepare import MergeContext


def _emit_to_stderr(line: str) -> None:
    print(line, file=sys.stderr, flush=True)


@dataclass(frozen=True)
class QueueLandingOutcome:
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


def _fail_landing(
    pr_num: str, error: str, warnings, *, exit_code: int = 1
) -> QueueLandingOutcome:
    return QueueLandingOutcome(
        ok=False, exit_code=exit_code, pr_num=pr_num, error=error, warnings=warnings
    )


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
        not_admitted = verify_landing_admitted(
            ctx, pr_num, target=target, sleep=sleep
        )
        if not_admitted:
            return _fail_landing(
                pr_num,
                not_admitted,
                tuple(warnings),
                exit_code=RECOVERABLE_QUEUE_EXIT_CODE,
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
    refusal = wait_for_queue_landing(
        ctx,
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
        warnings=warnings,
    )
    if refusal is not None:
        return _fail_landing(
            pr_num,
            refusal.error,
            tuple(warnings),
            exit_code=refusal.exit_code,
        )

    close_out = record_landing(
        ctx,
        item_id=item_id,
        commit_sha=commit_sha,
        pr_num=pr_num,
        member_snapshot=tuple(dict.fromkeys((*member_refs, public_ref))),
        drift_check=drift_receipt(drift),
    )
    warnings.extend(close_out.warnings)
    ci_refusal = close_out.ci_evidence_refusal(pr_num, resume_command)
    if ci_refusal:
        return _fail_landing(
            pr_num, ci_refusal,
            tuple(warnings), exit_code=RECOVERABLE_QUEUE_EXIT_CODE,
        )
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
