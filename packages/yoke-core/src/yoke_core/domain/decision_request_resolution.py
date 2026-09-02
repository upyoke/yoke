"""Authorized decision resolution and explicit subject-ended withdrawal."""

from __future__ import annotations

from typing import Any, Optional

from yoke_core.domain.db_helpers import iso8601_now
from yoke_core.domain.decision_request_contract import (
    REQUEST_RESOLVED_EVENT,
    REQUEST_WITHDRAWN_EVENT,
)
from yoke_core.domain.decision_request_events import append_decision_event
from yoke_core.domain.decision_request_subject_state import (
    require_decision_request_subject_ended,
)
from yoke_core.domain.decision_requests import (
    _authority_reason,
    _p,
    _request_row,
)


def resolve_decision_request(
    conn: Any,
    request_id: int,
    *,
    actor_id: int,
    action: str,
    note: Optional[str] = None,
    session_id: str = "",
    resolved_at: Optional[str] = None,
) -> dict[str, Any]:
    """Resolve after re-evaluating the role/name authority union."""
    request = _request_row(conn, request_id)
    if request["status"] != "pending":
        raise ValueError(f"decision request {request_id} is {request['status']}")
    if action not in request["actions"]:
        raise ValueError(
            f"{request['kind']} accepts actions: {', '.join(request['actions'])}"
        )
    if action == "request_changes" and not (note or "").strip():
        raise ValueError("request_changes requires a note")
    if note is not None and len(note) > 4000:
        raise ValueError("resolution note must be at most 4000 characters")
    if _authority_reason(conn, request_id, actor_id) is None:
        raise PermissionError(
            f"actor {actor_id} is not authorized for decision request {request_id}"
        )
    p = _p(conn)
    stamp = resolved_at or iso8601_now()
    cursor = conn.execute(
        "UPDATE decision_requests SET status = 'resolved', "
        f"resolution_action = {p}, resolution_actor_id = {p}, "
        f"resolution_note = {p}, resolved_at = {p} "
        f"WHERE id = {p} AND status = 'pending'",
        (action, actor_id, note, stamp, request_id),
    )
    if int(cursor.rowcount or 0) != 1:
        raise ValueError(f"decision request {request_id} is no longer pending")
    if request["kind"] == "qa_needs_review":
        from yoke_core.domain.schema_common import _table_exists
        from yoke_core.domain.qa_review_requests import (
            apply_qa_review_resolution,
        )

        if _table_exists(conn, "qa_requirements"):
            apply_qa_review_resolution(
                conn,
                requirement_id=int(request["subject_key"]),
                action=action,
                actor_id=actor_id,
                note=note,
                resolved_at=stamp,
            )
    append_decision_event(
        conn,
        REQUEST_RESOLVED_EVENT,
        actor_id=actor_id,
        session_id=session_id,
        project_id=request["project_id"],
        org_id=request["org_id"],
        context={
            "request_id": request_id,
            "kind": request["kind"],
            "action": action,
            "note": note,
        },
        created_at=stamp,
    )
    conn.commit()
    return _request_row(conn, request_id)


def withdraw_decision_request(
    conn: Any,
    request_id: int,
    *,
    reason: str,
    actor_id: Optional[int] = None,
    session_id: str = "",
    withdrawn_at: Optional[str] = None,
) -> dict[str, Any]:
    """Withdraw an open request explicitly when its subject ends."""
    if not reason.strip() or len(reason) > 1000:
        raise ValueError("withdrawal reason must contain 1 to 1000 characters")
    request = _request_row(conn, request_id)
    if request["status"] != "pending":
        raise ValueError(f"decision request {request_id} is {request['status']}")
    if actor_id is None or _authority_reason(conn, request_id, actor_id) is None:
        raise PermissionError(
            f"actor {actor_id} is not authorized to withdraw "
            f"decision request {request_id}"
        )
    return withdraw_for_ended_subject(
        conn,
        request_id,
        reason=reason,
        actor_id=actor_id,
        session_id=session_id,
        withdrawn_at=withdrawn_at,
    )


def withdraw_for_ended_subject(
    conn: Any,
    request_id: int,
    *,
    reason: str,
    actor_id: Optional[int] = None,
    session_id: str = "",
    withdrawn_at: Optional[str] = None,
    commit: bool = True,
) -> dict[str, Any]:
    """Withdraw a pending request whose typed subject has verifiably ended.

    This is the write every withdrawal lands through. The operator surface
    adds an authority check on top of it; a system disposition -- the event
    that ended the subject releasing what it had asked a human -- has no
    deciding actor and passes none. Neither can withdraw a live subject,
    because the subject-state contract below is re-evaluated either way.
    """
    if not reason.strip() or len(reason) > 1000:
        raise ValueError("withdrawal reason must contain 1 to 1000 characters")
    request = _request_row(conn, request_id)
    if request["status"] != "pending":
        raise ValueError(f"decision request {request_id} is {request['status']}")
    p = _p(conn)
    stamp = withdrawn_at or iso8601_now()
    subject_end_evidence = require_decision_request_subject_ended(
        conn,
        request,
        observed_at=stamp,
    )
    cursor = conn.execute(
        "UPDATE decision_requests SET status = 'withdrawn', "
        f"withdrawal_reason = {p}, withdrawn_at = {p} "
        f"WHERE id = {p} AND status = 'pending'",
        (reason.strip(), stamp, request_id),
    )
    if int(cursor.rowcount or 0) != 1:
        raise ValueError(f"decision request {request_id} is no longer pending")
    append_decision_event(
        conn,
        REQUEST_WITHDRAWN_EVENT,
        actor_id=actor_id,
        session_id=session_id,
        project_id=request["project_id"],
        org_id=request["org_id"],
        context={
            "request_id": request_id,
            "kind": request["kind"],
            "reason": reason.strip(),
            "subject_end_evidence": subject_end_evidence,
        },
        created_at=stamp,
    )
    if commit:
        conn.commit()
    return _request_row(conn, request_id)


__all__ = [
    "resolve_decision_request",
    "withdraw_decision_request",
    "withdraw_for_ended_subject",
]
