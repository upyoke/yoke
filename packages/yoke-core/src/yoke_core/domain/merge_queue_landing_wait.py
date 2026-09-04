"""Wait for one queued pull request through its server landing record."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Optional

from yoke_contracts.api.function_call import TargetRef
from yoke_core.domain import control_plane_function_degradation
from yoke_core.domain.github_poll_schedule import (
    PollSchedule,
    STEADY_SCHEDULE,
    next_read_delay,
)
from yoke_core.domain.merge_queue_entry_checks import entry_checks_refusal
from yoke_core.domain.merge_queue_landing_record import (
    LandingRecord,
    record_from_payload,
)
from yoke_core.domain.merge_queue_landing_timeout import timeout_message
from yoke_core.domain.merge_queue_landing_record_state import (
    CLOSED_UNMERGED,
    CONFLICTED,
    ENTRY_CHECKS_FAILED,
    LANDED,
    PENDING,
    STALLED,
)
from yoke_core.domain.session_liveness_pump import SessionLivenessPump


# Exit 9 is recoverable; red required checks are terminal (exit 1).
RECOVERABLE_QUEUE_EXIT_CODE = 9
DEFAULT_DEADLINE_SECONDS = 45.0 * 60.0
POLL_LINE_PREFIX = "Queue landing:"
OBSERVE_FUNCTION_ID = "merge_queue.landing.observe"


@dataclass(frozen=True)
class WaitRefusal:
    """Why a landing wait ended without a merge, and how recoverable it is."""

    error: str
    exit_code: int = 1


def _response_error(response: Any) -> str:
    error = getattr(response, "error", None)
    return str(getattr(error, "message", None) or "no reason given")


def _read_server_record(
    dispatch: Callable[..., Any],
    *,
    item_id: int,
    announce: Callable[[str], None],
) -> tuple[LandingRecord | None, dict[str, Any], str]:
    """Refresh the project if due and read this lane through one function."""
    response = control_plane_function_degradation.dispatch_through_paired_admin_on_skew(
        function_id=OBSERVE_FUNCTION_ID,
        target=TargetRef(kind="item", item_id=int(item_id)),
        payload={},
        announce=announce,
        dispatch=dispatch,
    )
    if not getattr(response, "success", False):
        return None, {}, _response_error(response)
    result = dict(getattr(response, "result", None) or {})
    try:
        record = record_from_payload(result.get("record"))
    except (KeyError, TypeError, ValueError) as exc:
        return None, result, f"landing record response was invalid: {exc}"
    return record, result, ""


def _stale_refusal(
    *,
    pr_num: str,
    result: dict[str, Any],
    record: LandingRecord | None,
) -> WaitRefusal:
    refresh = result.get("refresh") or {}
    observed_at = record.observed_at if record is not None else "never"
    completed_at = str(refresh.get("completed_at") or "never")
    last_error = str(refresh.get("last_error") or "none")
    return WaitRefusal(
        "landing_record_stale: the server-side record for pull request "
        f"{pr_num} was last refreshed at {observed_at}; the project refresh "
        f"last completed at {completed_at} (error={last_error}). Verify the "
        "control plane can reach GitHub and re-run `yoke merge item`; the "
        "waiting lane must not substitute local gh/git polling.",
        RECOVERABLE_QUEUE_EXIT_CODE,
    )


def _record_refusal(
    record: LandingRecord,
    *,
    pr_num: str,
    target: str,
) -> WaitRefusal | None:
    if record.state in (LANDED, PENDING):
        return None
    if record.state == ENTRY_CHECKS_FAILED:
        return WaitRefusal(
            entry_checks_refusal(
                pr_num=pr_num,
                head_sha=record.head_sha,
                narrative=record.narrative,
                disarm_note=record.disarm_note
                or "server-side merge-when-ready disarm was not recorded",
                failed=record.failed_checks,
            )
        )
    if record.state == CLOSED_UNMERGED:
        return WaitRefusal(
            f"pull request {pr_num} closed without merging — observed "
            f"{record.narrative}; reopen or recreate it before re-entering "
            "the queue"
        )
    if record.state == CONFLICTED:
        return WaitRefusal(
            f"pull request {pr_num} has merge conflicts — observed "
            f"{record.narrative}; rebase the lane onto {target}, re-run the "
            "verification gate, and re-run `yoke merge item`",
            RECOVERABLE_QUEUE_EXIT_CODE,
        )
    if record.state == STALLED:
        return WaitRefusal(
            f"the merge queue is no longer driving pull request {pr_num} — "
            f"observed {record.narrative}; rebase the lane onto {target}, "
            "re-run the verification gate, and re-run `yoke merge item`. "
            "Re-running the landing is safe: it converges on the merge if "
            "one happens meanwhile",
            RECOVERABLE_QUEUE_EXIT_CODE,
        )
    return WaitRefusal(
        f"landing_record_invalid: pull request {pr_num} has unknown server "
        f"state {record.state!r}; deploy a build with matching landing-record "
        "contracts and re-run `yoke merge item`",
        RECOVERABLE_QUEUE_EXIT_CODE,
    )


def wait_for_queue_landing(
    *,
    pr_num: str,
    target: str,
    item_id: int,
    public_ref: str,
    resume_command: str,
    dispatch: Callable[..., Any],
    sleep: Callable[[float], None],
    monotonic: Callable[[], float],
    schedule: PollSchedule = STEADY_SCHEDULE,
    deadline_seconds: float = DEFAULT_DEADLINE_SECONDS,
    liveness: Optional[SessionLivenessPump] = None,
    emit: Callable[[str], None],
) -> Optional[WaitRefusal]:
    """Consume server observations until the pull request lands."""
    started = monotonic()
    deadline = started + deadline_seconds
    pump = liveness if liveness is not None else SessionLivenessPump()
    last_seen = ""
    last_announced = ""
    now = started
    while now < deadline:
        pump.tick()
        record, result, record_error = _read_server_record(
            dispatch,
            item_id=item_id,
            announce=emit,
        )
        if record_error:
            return WaitRefusal(
                "landing_record_refresh_failed: the waiting lane could not "
                f"read the server record for pull request {pr_num}: "
                f"{record_error}. Deploy or repair the control-plane function "
                f"{OBSERVE_FUNCTION_ID} and re-run `yoke merge item`; do not "
                "fall back to local gh/git polling.",
                RECOVERABLE_QUEUE_EXIT_CODE,
            )
        if bool(result.get("stale")):
            return _stale_refusal(pr_num=pr_num, result=result, record=record)
        if record is None:
            pump.wait(next_read_delay(now - started, schedule), sleep=sleep)
            now = monotonic()
            continue
        if record.pr_number != str(pr_num):
            return WaitRefusal(
                "landing_record_mismatch: the server returned pull request "
                f"{record.pr_number} while this lane is waiting for {pr_num}; "
                "re-run `yoke merge item` after the control-plane marker is "
                "repaired.",
                RECOVERABLE_QUEUE_EXIT_CODE,
            )
        narrative = record.narrative
        if narrative:
            last_seen = narrative
            if narrative != last_announced:
                last_announced = narrative
                emit(
                    f"{POLL_LINE_PREFIX} {narrative} "
                    f"(recorded: {record.observed_at}; elapsed: "
                    f"{int(now - started)}s)"
                )
        refusal = _record_refusal(record, pr_num=pr_num, target=target)
        if record.state == LANDED:
            return None
        if refusal is not None:
            return refusal
        pump.wait(next_read_delay(now - started, schedule), sleep=sleep)
        now = monotonic()
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
    "OBSERVE_FUNCTION_ID",
    "POLL_LINE_PREFIX",
    "RECOVERABLE_QUEUE_EXIT_CODE",
    "WaitRefusal",
    "wait_for_queue_landing",
]
