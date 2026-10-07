"""The candidate head a queue landing merged, read from its landing record.

The merge receipt has to name that commit. ``item_worktrees.commit_sha`` is a
different fact: it is the head the lane last cached, and a rebase before
landing — or a correction that lands after an earlier merge — leaves the
cache naming a commit the queue did not merge.
"""

from __future__ import annotations

from typing import Any, Callable, Optional

from yoke_core.domain.public_item_target import public_item_target
from yoke_core.domain import control_plane_function_degradation
from yoke_core.domain.merge_queue_landing_record import record_from_payload
from yoke_core.domain.merge_queue_landing_record_state import LANDED
from yoke_core.domain.merge_queue_landing_wait import OBSERVE_FUNCTION_ID


def landed_candidate_head(
    public_ref: str,
    *,
    dispatch: Optional[Callable[..., Any]] = None,
) -> tuple[str, str]:
    """Return ``(head, "")`` or ``("", reason)``.

    ``head`` is the pull-request head stored on the landing record when the
    merge was observed. A caller records that head. A reason means the
    record did not name one, and a cached lane head is not a substitute.
    """
    if dispatch is None:
        from yoke_core.api.service_client_structured_api_adapter import (
            call_dispatcher,
        )

        dispatch = call_dispatcher
    response = control_plane_function_degradation.dispatch_through_paired_admin_on_skew(
        function_id=OBSERVE_FUNCTION_ID,
        target=public_item_target(public_ref),
        payload={},
        announce=lambda _line: None,
        dispatch=dispatch,
    )
    if not getattr(response, "success", False):
        error = getattr(response, "error", None)
        detail = str(getattr(error, "message", None) or "no reason given")
        return "", (
            f"landing record unreadable: {detail}. Re-run the same close-out "
            f"once {OBSERVE_FUNCTION_ID} can read it."
        )
    result = dict(getattr(response, "result", None) or {})
    try:
        record = record_from_payload(result.get("record"))
    except (KeyError, TypeError, ValueError) as exc:
        return "", (
            f"landing record response was invalid: {exc}. Re-run the same "
            f"close-out once {OBSERVE_FUNCTION_ID} returns a landing record."
        )
    if record is None:
        return "", (
            "landing record has no observation for this item. Re-run the "
            f"same close-out once {OBSERVE_FUNCTION_ID} has recorded the "
            "merged pull request."
        )
    if record.state != LANDED:
        return "", (
            f"landing record state is {record.state!r}, not {LANDED!r}. "
            "Re-run the same close-out once the record says the pull "
            "request merged."
        )
    head = str(record.head_sha or "").strip()
    if not head:
        return "", (
            "landing record says the pull request merged but names no "
            "candidate head. Re-run the same close-out once the observation "
            "includes the merged pull request head."
        )
    return head, ""


__all__ = ["landed_candidate_head"]
