"""Server-side writes for the merge-queue landing marker on one item.

Four columns on ``items`` say which pull request an item lands through and
how far that landing has got: the pull request number, the queue admission,
the landing, and the notification. Three writes own them — the pull request
is recorded when it is opened, the queue admission after either landing route
arms it, and the whole marker is cleared at close-out.

The columns themselves are written by
:func:`yoke_core.domain.merge_queue_landing_marker.point_item_at_pull_request`,
shared with the operator repoint so the two can never disagree.

They are separate calls because the moments are separate and only the first
is common to both landing routes. Recording the pull request at open time is
what lets the control-plane landing observer
(:mod:`yoke_core.domain.merge_queue_landing_observer`) find a merge whose
waiting process died, so an item is never merged on GitHub and silent here.

These are ``adapter_status='internal'`` merge-boundary glue with the same
session-optional, claim-free posture as the done-transition writes they sit
beside: the merge subprocess may resolve no ambient harness session, and the
claim ceremony is enforced upstream by the status flip.
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field, ValidationError

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)
from yoke_core.domain.merge_queue_landing_marker import (
    point_item_at_pull_request,
)
from yoke_core.domain.merge_queue_landing_record import delete_landing_record
from yoke_contracts.public_ref import ITEM_NOT_FOUND


class MarkLandingPendingRequest(BaseModel):
    pr_number: str = Field(..., min_length=1)
    enqueued_at: str = Field(..., min_length=1)


class MarkLandingPendingResponse(BaseModel):
    item_id: int
    pr_number: str
    enqueued_at: str
    landed_at: str = ""
    notified_at: str = ""


class RecordLandingPullRequestRequest(BaseModel):
    pr_number: str = Field(..., min_length=1)


class RecordLandingPullRequestResponse(BaseModel):
    item_id: int
    pr_number: str
    enqueued_at: str = ""
    landed_at: str = ""
    notified_at: str = ""


class ClearLandingPendingRequest(BaseModel):
    pass


class ClearLandingPendingResponse(BaseModel):
    item_id: int
    cleared: bool


def _err(code: str, message: str) -> HandlerOutcome:
    return HandlerOutcome(
        primary_success=False,
        error=FunctionError(code=code, message=message),
    )


def _connect_rw() -> Any:
    from yoke_core.domain import db_helpers

    return db_helpers.connect()


def _placeholder(conn: Any) -> str:
    from yoke_core.domain import db_backend

    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _require_item_id(request: FunctionCallRequest) -> Optional[int]:
    if request.target.item_id is None:
        return None
    return int(request.target.item_id)


def _write_landing_marker(
    item_id: int,
    pr_number: str,
    *,
    enqueued_at: str,
    failure_code: str,
) -> HandlerOutcome:
    """Point the item at ``pr_number`` and return the four landing facts."""
    try:
        with _connect_rw() as conn:
            marker = point_item_at_pull_request(
                conn, item_id, pr_number, enqueued_at=enqueued_at
            )
    except Exception as exc:  # noqa: BLE001 - surfaced to the merge boundary
        return _err(failure_code, str(exc))
    if marker is None:
        return _err("target_not_found", ITEM_NOT_FOUND)
    return HandlerOutcome(
        result_payload={"item_id": item_id, **marker},
        primary_success=True,
    )


def handle_record_landing_pull_request(
    request: FunctionCallRequest,
) -> HandlerOutcome:
    """Record which pull request this item lands through, at open time.

    Recorded when the pull request is opened rather than when the queue
    takes it, because that is the only moment both landing routes share.
    Both routes mark their queue admission afterwards; a worker holding the
    landing does so before it starts its server-record wait. This first write
    still matters before that point: if
    the process dies between opening and arming, the observer can record a
    merge without inventing a queue admission. It declares no admission of
    its own.
    """
    item_id = _require_item_id(request)
    if item_id is None:
        return _err(
            "target_invalid",
            "landing_pull_request.record requires target.item_id",
        )
    try:
        body = RecordLandingPullRequestRequest.model_validate(request.payload)
    except ValidationError as exc:
        return _err("payload_invalid", f"landing pull request payload invalid: {exc}")
    return _write_landing_marker(
        item_id,
        body.pr_number,
        enqueued_at="",
        failure_code="landing_pull_request_record_failed",
    )


def handle_mark_landing_pending(request: FunctionCallRequest) -> HandlerOutcome:
    """Persist one idempotent merge-queue handoff marker."""
    item_id = _require_item_id(request)
    if item_id is None:
        return _err("target_invalid", "landing_pending.mark requires target.item_id")
    try:
        body = MarkLandingPendingRequest.model_validate(request.payload)
    except ValidationError as exc:
        return _err("payload_invalid", f"landing marker payload invalid: {exc}")
    return _write_landing_marker(
        item_id,
        body.pr_number,
        enqueued_at=body.enqueued_at,
        failure_code="landing_pending_mark_failed",
    )


def handle_clear_landing_pending(request: FunctionCallRequest) -> HandlerOutcome:
    """Clear the queue handoff only after item close-out succeeds."""
    item_id = _require_item_id(request)
    if item_id is None:
        return _err("target_invalid", "landing_pending.clear requires target.item_id")
    try:
        ClearLandingPendingRequest.model_validate(request.payload)
        with _connect_rw() as conn:
            p = _placeholder(conn)
            cursor = conn.execute(
                "UPDATE items SET merge_queue_pr_number = NULL, "
                "merge_queue_enqueued_at = NULL, merge_queue_landed_at = NULL, "
                f"merge_queue_notified_at = NULL WHERE id = {p}",
                (item_id,),
            )
            delete_landing_record(conn, item_id)
            conn.commit()
            cleared = bool(cursor.rowcount)
    except ValidationError as exc:
        return _err("payload_invalid", f"landing marker payload invalid: {exc}")
    except Exception as exc:  # noqa: BLE001 - advisory close-out warning
        return _err("landing_pending_clear_failed", str(exc))
    return HandlerOutcome(
        result_payload={"item_id": item_id, "cleared": cleared},
        primary_success=True,
    )


__all__ = [
    "ClearLandingPendingRequest",
    "ClearLandingPendingResponse",
    "MarkLandingPendingRequest",
    "MarkLandingPendingResponse",
    "RecordLandingPullRequestRequest",
    "RecordLandingPullRequestResponse",
    "handle_clear_landing_pending",
    "handle_mark_landing_pending",
    "handle_record_landing_pull_request",
]
