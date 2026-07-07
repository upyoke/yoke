"""Execution-owned claim release and operator override flows."""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from yoke_core.domain.lifecycle import ItemStatus

from . import db_backend
from . import sessions_analytics as _sa
from .sessions_analytics import EVENT_WORK_RELEASED, SessionError
from .sessions_lifecycle_release_failure import (
    RELEASE_FAILURE_DOMAIN_ERROR,
    diagnose_release_miss,
    diagnose_target_release_miss,
    emit_release_failed,
    emit_target_release_failed,
    read_item_status,
)
from .sessions_lifecycle_release_precondition import emit_release_refused, evaluate_release_precondition
from .sessions_queries import _now_iso, normalize_claim_item_id
from .work_claim_targets import (
    TARGET_KIND_EPIC_TASK,
    TARGET_KIND_ITEM,
    TARGET_KIND_PROCESS,
    WorkClaimTarget,
    make_item_target,
)

_RELEASE_REASON_SCHEMA_MAP: Dict[str, str] = {
    "handoff-to-polish": "handed_off",
    "handoff-to-usher": "handed_off",
    "handed_off": "handed_off",
    "handoff": "handed_off",
    "idea-complete": "handed_off",
    "finalize-exit": "released",
    "offer-override": "released",
    "released": "released",
    "completed": "completed",
    "reclaimed": "reclaimed",
    "expired": "expired",
    "session_ended": "session_ended",
    "agent_handoff_session_scoped": "handed_off",
}


def _canonical_release_reason(raw: str) -> str:
    """Map a caller-supplied reason to the schema-enum release_reason."""
    if not raw:
        return "released"
    return _RELEASE_REASON_SCHEMA_MAP.get(raw, "released")


_COMPLETED_RELEASE_ALLOWED_ITEM_STATUSES = frozenset({
    ItemStatus.REFINED_IDEA.value,
    ItemStatus.PLAN_DRAFTED.value,
    ItemStatus.PLANNED.value,
    ItemStatus.REVIEWED_IMPLEMENTATION.value,
    ItemStatus.IMPLEMENTED.value,
    ItemStatus.RELEASE.value,
    ItemStatus.DONE.value,
})


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _validate_completed_release_status(
    conn: Any,
    item_id_int: int,
    canonical_reason: str,
) -> None:
    """Reject `completed` releases while an item is still mid-command."""
    if canonical_reason != "completed":
        return

    try:
        row = conn.execute(
            f"SELECT status FROM items WHERE id = {_p(conn)}",
            (item_id_int,),
        ).fetchone()
    except db_backend.database_error_types(conn):
        return

    if row is None:
        return

    status = row["status"] if hasattr(row, "keys") else row[0]
    if status in _COMPLETED_RELEASE_ALLOWED_ITEM_STATUSES:
        return

    raise ValueError(
        f"Cannot release YOK-{item_id_int} with reason 'completed' while "
        f"status is '{status}'. Advance the item to its successful handoff "
        f"status first."
    )


def release_item_claim_for_execution(
    conn: Any,
    session_id: str,
    item_id: str,
    reason: str,
) -> Dict[str, Any]:
    """Release an execution-owned item claim and clear focus atomically.

    Convenience wrapper around the typed
    :func:`release_work_claim_for_execution` for callers that still
    speak in raw item-id strings. Equivalent to passing
    ``target=make_item_target(int(item_id))``.
    """
    normalized = normalize_claim_item_id(item_id)
    if not normalized.isdigit():
        raise ValueError(
            f"release_item_claim_for_execution requires a numeric item id; got {item_id!r}"
        )
    target = make_item_target(int(normalized))
    return release_work_claim_for_execution(conn, session_id, target, reason)


def release_work_claim_for_execution(
    conn: Any,
    session_id: str,
    target: WorkClaimTarget,
    reason: str,
    *,
    allow_non_terminal: bool = False,
) -> Dict[str, Any]:
    """Release an execution-owned typed claim and clear focus atomically.

    On success: returns ``{"released": True, "claim_id", "reason_intent",
    "reason_stored"}`` and emits ``WorkReleased``.
    On any non-success path (``not_owned`` / ``already_terminal`` /
    ``item_not_found`` / ``domain_error``): returns ``{"released": False,
    "failure_reason", "holder_session_id", "target_status", ...}`` AND
    emits ``ItemClaimReleaseFailed`` with the same payload. Validation
    failures still raise ``ValueError`` for the caller after emitting.
    Generic attribution helpers must NOT be substituted here.
    """
    now = _now_iso()
    claim_row = _find_active_claim(conn, session_id, target)
    target_label = target.render()

    if claim_row is None:
        failure_reason, holder = diagnose_target_release_miss(conn, target)
        target_status: Optional[str] = None
        if target.kind == TARGET_KIND_ITEM and target.item_id is not None:
            target_status = read_item_status(conn, str(target.item_id))
        emit_target_release_failed(
            caller_session_id=session_id,
            target=target,
            holder_session_id=holder,
            failure_reason=failure_reason,
            target_status=target_status,
            reason_intent=reason,
        )
        return {
            "released": False,
            "failure_reason": failure_reason,
            "holder_session_id": holder,
            "target_status": target_status,
            "target_kind": target.kind,
            "target_label": target_label,
            "reason_intent": reason,
        }

    claim_id = claim_row["id"]
    precondition = evaluate_release_precondition(
        conn, session_id=session_id, target=target,
        release_reason_intent=reason, allow_non_terminal=allow_non_terminal)
    if not precondition.allowed:
        return emit_release_refused(session_id=session_id, target=target,
            claim_id=int(claim_id), reason=reason, precondition=precondition)
    canonical_reason = _canonical_release_reason(reason)
    if target.kind == TARGET_KIND_ITEM and target.item_id is not None:
        try:
            _validate_completed_release_status(conn, target.item_id, canonical_reason)
        except ValueError as exc:
            target_status = read_item_status(conn, str(target.item_id))
            emit_target_release_failed(
                caller_session_id=session_id,
                target=target,
                holder_session_id=session_id,
                failure_reason=RELEASE_FAILURE_DOMAIN_ERROR,
                target_status=target_status,
                reason_intent=reason,
                extra={"error": str(exc), "claim_id": claim_id},
            )
            raise

    if target.kind == TARGET_KIND_ITEM and target.item_id is not None:
        _maybe_clear_current_item(conn, session_id, str(target.item_id))

    conn.execute(
        f"UPDATE work_claims SET released_at = {_p(conn)}, "
        f"release_reason = {_p(conn)} WHERE id = {_p(conn)}",
        (now, canonical_reason, claim_id),
    )
    # The caller's release intent is first-class claim state — the
    # released row persists and the frontier defense reads it from here.
    from .claim_chain_state import record_release_intent, touch_epic_task_activity

    record_release_intent(conn, claim_id=int(claim_id), intent=reason)
    if target.kind == TARGET_KIND_EPIC_TASK:
        touch_epic_task_activity(
            conn, epic_id=target.epic_id, task_num=target.task_num, at=now,
        )
    if target.kind == TARGET_KIND_PROCESS:
        _release_linked_path_claims(conn, claim_id, now, canonical_reason)
    conn.commit()

    item_id_for_event: Optional[str] = None
    task_num_for_event: Optional[int] = None
    context: Dict[str, Any] = {
        "claim_id": claim_id,
        "release_reason": canonical_reason,
        "release_reason_intent": reason,
        "execution_owned": True,
        "target_kind": target.kind,
    }
    if target.kind == TARGET_KIND_ITEM:
        item_id_for_event = str(target.item_id)
    elif target.kind == TARGET_KIND_EPIC_TASK:
        item_id_for_event = str(target.epic_id)
        task_num_for_event = target.task_num
    else:
        context["process_key"] = target.process_key
        context["conflict_group"] = target.conflict_group

    _sa._emit_session_event(
        EVENT_WORK_RELEASED,
        session_id=session_id,
        item_id=item_id_for_event,
        task_num=task_num_for_event,
        context=context,
    )

    if target.kind == TARGET_KIND_ITEM and target.item_id is not None:
        from .idea_claim_events import emit_if_idea_release

        emit_if_idea_release(
            conn,
            session_id=session_id,
            target_item_id=int(target.item_id),
            claim_id=int(claim_id),
            release_reason_intent=reason,
            released_at=now,
        )

    return {
        "released": True,
        "claim_id": claim_id,
        "reason_intent": reason,
        "reason_stored": canonical_reason,
        "target_kind": target.kind,
        "target_label": target_label,
    }


def _find_active_claim(
    conn: Any,
    session_id: str,
    target: WorkClaimTarget,
) -> Optional[Any]:
    if target.kind == TARGET_KIND_ITEM:
        return conn.execute(
            "SELECT id FROM work_claims "
            f"WHERE session_id = {_p(conn)} AND target_kind='item' AND item_id = {_p(conn)} "
            "AND released_at IS NULL "
            "ORDER BY claimed_at DESC, id DESC LIMIT 1",
            (session_id, target.item_id),
        ).fetchone()
    if target.kind == TARGET_KIND_EPIC_TASK:
        return conn.execute(
            "SELECT id FROM work_claims "
            f"WHERE session_id = {_p(conn)} AND target_kind='epic_task' AND epic_id = {_p(conn)} "
            f"AND task_num = {_p(conn)} AND released_at IS NULL "
            "ORDER BY claimed_at DESC, id DESC LIMIT 1",
            (session_id, target.epic_id, target.task_num),
        ).fetchone()
    return conn.execute(
        "SELECT id FROM work_claims "
        f"WHERE session_id = {_p(conn)} AND target_kind='process' AND process_key = {_p(conn)} "
        "AND released_at IS NULL "
        "ORDER BY claimed_at DESC, id DESC LIMIT 1",
        (session_id, target.process_key),
    ).fetchone()


def _maybe_clear_current_item(
    conn: Any, session_id: str, item_id_text: str,
) -> None:
    """Clear current_item_id only when the focus points at this claim's item."""
    current_row = conn.execute(
        "SELECT current_item_id, current_item_set_at "
        f"FROM harness_sessions WHERE session_id = {_p(conn)}",
        (session_id,),
    ).fetchone()
    if current_row is None or current_row["current_item_id"] is None:
        return
    current = normalize_claim_item_id(str(current_row["current_item_id"]))
    if current == item_id_text:
        conn.execute(
            "UPDATE harness_sessions SET "
            f"recent_item_id = {_p(conn)}, recent_item_recorded_at = {_p(conn)}, "
            "current_item_id = NULL, current_item_set_at = NULL "
            f"WHERE session_id = {_p(conn)}",
            (current_row["current_item_id"], current_row["current_item_set_at"], session_id),
        )


def _release_linked_path_claims(
    conn: Any,
    work_claim_id: int,
    now: str,
    canonical_reason: str,
) -> List[int]:
    """Release non-terminal path claims linked to a process work-claim.

    The release path lives here; process work-claims own linked path
    claims (registered via path_claims_register_process) and must free
    the integration boundary in lockstep. Returns the released path-
    claim ids so the parent ``WorkReleased`` event can audit the
    cascade. Tolerant of fixtures without ``path_claims`` -- empty list.
    """
    try:
        rows = conn.execute(
            f"SELECT id FROM path_claims WHERE work_claim_id = {_p(conn)} "
            "AND released_at IS NULL AND cancelled_at IS NULL",
            (work_claim_id,),
        ).fetchall()
    except db_backend.operational_error_types(conn):
        return []
    released_ids: List[int] = []
    for row in rows:
        cid = int(row[0])
        conn.execute(
            f"UPDATE path_claims SET state = 'released', released_at = {_p(conn)}, "
            f"release_reason = {_p(conn)} WHERE id = {_p(conn)}",
            (now, f"work-claim-released:{canonical_reason}", cid),
        )
        released_ids.append(cid)
    return released_ids


from .sessions_lifecycle_release_bulk import release_all_claims  # noqa: E402,F401
from .sessions_lifecycle_release_operator import operator_override_release_claim  # noqa: E402,F401
