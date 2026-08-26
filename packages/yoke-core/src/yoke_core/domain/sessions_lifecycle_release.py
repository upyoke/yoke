"""Execution-owned claim release and operator override flows."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from . import db_backend, project_identity
from . import sessions_analytics as _sa  # noqa: F401 - patch-compatible event seam
from .sessions_claim_lifecycle_lock import lock_session_rows_for_claim_lifecycle
from .sessions_lifecycle_claim_release import (
    build_claim_release_post_commit_receipt,
    emit_claim_release_post_commit,
    find_active_claim,
)
from .sessions_lifecycle_release_failure import (
    RELEASE_FAILURE_DOMAIN_ERROR,
    diagnose_target_release_miss,
    emit_target_release_failed,
    read_item_status,
)
from .sessions_lifecycle_release_precondition import (
    emit_release_refused,
    evaluate_release_precondition,
)
from .sessions_lifecycle_release_events import (
    POST_COMMIT_RECEIPT_KEY as _POST_COMMIT_RECEIPT_KEY,
)
from .sessions_queries import _now_iso, normalize_claim_item_id
from .sessions_render_attribution import release_current_item_focus
from .workflow_runtime import load_item_workflow_runtime
from .work_claim_targets import (
    TARGET_KIND_EPIC_TASK,
    TARGET_KIND_ITEM,
    TARGET_KIND_PROCESS,
    WorkClaimTarget,
    make_item_target,
)
from . import workflow_item_binding_lock as binding_lock

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
    try:
        workflow = load_item_workflow_runtime(conn, item_id_int)
    except Exception:
        return
    if workflow.allows_completed_claim_release(str(status)):
        return

    raise ValueError(
        f"Cannot release {project_identity.render_item_ref(conn, item_id_int)} with reason 'completed' while "
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


@binding_lock.rollback_workflow_binding_write_errors
def release_work_claim_for_execution(
    conn: Any,
    session_id: str,
    target: WorkClaimTarget,
    reason: str,
    *,
    allow_non_terminal: bool = False,
    commit: bool = True,
) -> Dict[str, Any]:
    """Release an execution-owned typed claim and clear focus atomically.

    On success: returns ``{"released": True, "claim_id", "reason_intent",
    "reason_stored"}`` and emits ``WorkReleased``.
    On any non-success path (``not_owned`` / ``already_terminal`` /
    ``item_not_found`` / ``domain_error``): returns ``{"released": False,
    "failure_reason", "holder_session_id", "target_status", ...}`` AND
    emits ``ItemClaimReleaseFailed`` with the same payload. Validation
    failures still raise ``ValueError`` for the caller after emitting.
    Generic attribution helpers must NOT be substituted here. ``commit=False``
    is reserved for an enclosing session-end transaction; it returns a private
    post-commit telemetry receipt instead of emitting success events.
    """
    lock_session_rows_for_claim_lifecycle(conn, (session_id,))
    binding_lock.lock_work_claim_target_workflow_binding(conn, target)
    now = _now_iso()
    claim_row = find_active_claim(conn, session_id, target)
    target_label = target.render()

    if claim_row is None:
        if commit:
            conn.commit()
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
        conn,
        session_id=session_id,
        target=target,
        release_reason_intent=reason,
        allow_non_terminal=allow_non_terminal,
    )
    if not precondition.allowed:
        if commit:
            conn.commit()
        return emit_release_refused(
            session_id=session_id,
            target=target,
            claim_id=int(claim_id),
            reason=reason,
            precondition=precondition,
        )
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
            conn,
            epic_id=target.epic_id,
            task_num=target.task_num,
            at=now,
        )
    if target.kind == TARGET_KIND_PROCESS:
        _release_linked_path_claims(conn, claim_id, now, canonical_reason)

    receipt = build_claim_release_post_commit_receipt(
        session_id=session_id,
        target=target,
        claim_id=int(claim_id),
        canonical_reason=canonical_reason,
        reason=reason,
        released_at=now,
    )
    if commit:
        conn.commit()
        emit_claim_release_post_commit(conn, receipt)

    result = {
        "released": True,
        "claim_id": claim_id,
        "reason_intent": reason,
        "reason_stored": canonical_reason,
        "target_kind": target.kind,
        "target_label": target_label,
    }
    if not commit:
        result[_POST_COMMIT_RECEIPT_KEY] = receipt
    return result


def _maybe_clear_current_item(
    conn: Any,
    session_id: str,
    item_id_text: str,
) -> None:
    """Re-focus the session when the claim behind the focus is released.

    When focus points at this claim's item, archive it to
    ``recent_item_id`` and fall back to the newest still-active item
    claim (``release_current_item_focus``); a session holding several
    claims keeps pointing at real work instead of dropping to none.
    Focus naming a different item is left untouched.
    """
    current_row = conn.execute(
        f"SELECT current_item_id FROM harness_sessions WHERE session_id = {_p(conn)}",
        (session_id,),
    ).fetchone()
    if current_row is None or current_row["current_item_id"] is None:
        return
    current = normalize_claim_item_id(str(current_row["current_item_id"]))
    if current == normalize_claim_item_id(item_id_text):
        release_current_item_focus(conn, session_id, commit=False)


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
            f"SELECT id FROM path_claims WHERE owner_kind = 'process' "
            f"AND owner_work_claim_id = {_p(conn)} AND state IN ('planned', 'blocked', 'active')",
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
