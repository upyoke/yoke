"""Client writes that record which pull request an item lands through.

Three moments write here, and they are deliberately separate calls. The
pull request is recorded when it is opened, because that is the only moment
both landing routes share and it is what makes a landing legible to the
control-plane observer
(:mod:`yoke_core.domain.merge_queue_landing_observer`) when the process
waiting for it dies. Both routes mark a queue admission: the handoff exits,
while the explicit waiter consumes the server record it refreshes. Close-out
clears the whole marker.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Callable

from yoke_contracts.api.function_call import TargetRef
from yoke_core.api.service_client_structured_api_adapter import call_dispatcher
from yoke_core.domain.session_message_types import timestamp, utc_now


def _response_error(response: Any, fallback: str) -> str:
    error = getattr(response, "error", None)
    return str(getattr(error, "message", None) or fallback)


def record_landing_pull_request(
    item_id: int,
    pr_number: str,
    *,
    dispatch: Callable[..., Any] = call_dispatcher,
) -> str:
    """Point the item at its landing pull request; return a warning on failure.

    Advisory on purpose: this only makes an already-open pull request
    findable later, so failing to record it must not fail the landing that
    is otherwise proceeding.
    """
    response = dispatch(
        function_id="merge_queue.landing_pull_request.record",
        target=TargetRef(kind="item", item_id=int(item_id)),
        payload={"pr_number": str(pr_number)},
    )
    if getattr(response, "success", False):
        return ""
    return _response_error(response, "landing pull request record failed")


def mark_landing_pending(
    item_id: int,
    pr_number: str,
    *,
    dispatch: Callable[..., Any] = call_dispatcher,
    now: datetime | None = None,
) -> tuple[str, str]:
    """Persist queue admission, returning ``(enqueued_at, error)``."""
    enqueued_at = timestamp(now or utc_now())
    response = dispatch(
        function_id="merge_queue.landing_pending.mark",
        target=TargetRef(kind="item", item_id=int(item_id)),
        payload={"pr_number": str(pr_number), "enqueued_at": enqueued_at},
    )
    if not getattr(response, "success", False):
        return "", _response_error(response, "landing marker write failed")
    result = getattr(response, "result", None) or {}
    return str(result.get("enqueued_at") or enqueued_at), ""


def clear_landing_pending(
    item_id: int,
    *,
    dispatch: Callable[..., Any] = call_dispatcher,
) -> str:
    """Clear a marker after close-out; return a warning on failure."""
    response = dispatch(
        function_id="merge_queue.landing_pending.clear",
        target=TargetRef(kind="item", item_id=int(item_id)),
        payload={},
    )
    if getattr(response, "success", False):
        return ""
    return _response_error(response, "landing marker clear failed")


__all__ = [
    "clear_landing_pending",
    "mark_landing_pending",
    "record_landing_pull_request",
]
