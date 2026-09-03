"""The inline poll that waits for one queued pull request to land.

Callers that keep their process alive through the landing wait here;
the durable handoff route exits instead and lets the control-plane
observer watch. Both read the same classifier, so a pull request that
leaves the queue or goes dirty ends either wait with the same named
refusal rather than an unbounded silence.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Optional

from yoke_core.domain.github_poll_schedule import (
    CI_SUITE_SCHEDULE,
    PollSchedule,
    next_read_delay,
)
from yoke_core.domain.merge_queue_entry_checks import (
    disarm_merge_when_ready,
    entry_checks_refusal,
)
from yoke_core.domain.merge_queue_landing_timeout import timeout_message
from yoke_core.domain.merge_queue_landing_verdict import (
    CLOSED_UNMERGED,
    CONFLICTED,
    ENTRY_CHECKS_FAILED,
    LANDED,
    STALLED,
    classify_landing,
)
from yoke_core.domain.session_liveness_pump import SessionLivenessPump
from yoke_core.engines.merge_worktree_prepare import MergeContext


# Exit 9 is recoverable; red required checks are terminal (exit 1).
RECOVERABLE_QUEUE_EXIT_CODE = 9

DEFAULT_DEADLINE_SECONDS = 45.0 * 60.0

POLL_LINE_PREFIX = "Queue landing:"


@dataclass(frozen=True)
class WaitRefusal:
    """Why a landing wait ended without a merge, and how recoverable it is."""

    error: str
    exit_code: int = 1


def wait_for_queue_landing(
    ctx: MergeContext,
    *,
    pr_num: str,
    target: str,
    item_id: int,
    public_ref: str,
    resume_command: str,
    dispatch: Callable[..., Any],
    sleep: Callable[[float], None],
    monotonic: Callable[[], float],
    schedule: PollSchedule = CI_SUITE_SCHEDULE,
    deadline_seconds: float = DEFAULT_DEADLINE_SECONDS,
    liveness: Optional[SessionLivenessPump] = None,
    emit: Callable[[str], None],
    warnings: list[str],
) -> Optional[WaitRefusal]:
    """Poll until the pull request merges; ``None`` means it landed."""
    started = monotonic()
    deadline = started + deadline_seconds
    pump = liveness if liveness is not None else SessionLivenessPump()
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
            return None
        if landing.kind == ENTRY_CHECKS_FAILED:
            return WaitRefusal(
                entry_checks_refusal(
                    pr_num=pr_num,
                    head_sha=landing.head_sha,
                    narrative=landing.narrative,
                    disarm_note=disarm_merge_when_ready(ctx, pr_num),
                )
            )
        if landing.kind == CLOSED_UNMERGED:
            return WaitRefusal(
                f"pull request {pr_num} closed without merging — observed "
                f"{landing.narrative}; reopen or recreate it before "
                "re-entering the queue"
            )
        if landing.kind == CONFLICTED:
            return WaitRefusal(
                f"pull request {pr_num} has merge conflicts — observed "
                f"{landing.narrative}; rebase the lane onto {target}, re-run "
                "the verification gate, and re-run `yoke merge item`",
                RECOVERABLE_QUEUE_EXIT_CODE,
            )
        if landing.kind == STALLED:
            return WaitRefusal(
                f"the merge queue is no longer driving pull request "
                f"{pr_num} — observed {landing.narrative}; rebase the lane "
                f"onto {target}, re-run the verification gate, and re-run "
                "`yoke merge item`. Re-running the landing is safe: it "
                "converges on the merge if one happens meanwhile",
                RECOVERABLE_QUEUE_EXIT_CODE,
            )
        pump.wait(next_read_delay(now - started, schedule), sleep=sleep)
        now = monotonic()
    # Poll-budget timeout is resumable: the claim is still held.
    return WaitRefusal(
        timeout_message(
            pr_num=pr_num,
            deadline_seconds=deadline_seconds,
            item_id=item_id,
            public_ref=public_ref,
            resume_command=resume_command,
            dispatch=dispatch,
            last_observed=last_seen,
        ),
        RECOVERABLE_QUEUE_EXIT_CODE,
    )


__all__ = [
    "DEFAULT_DEADLINE_SECONDS",
    "POLL_LINE_PREFIX",
    "RECOVERABLE_QUEUE_EXIT_CODE",
    "WaitRefusal",
    "wait_for_queue_landing",
]
