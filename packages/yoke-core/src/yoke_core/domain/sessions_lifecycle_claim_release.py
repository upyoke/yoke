"""Claim-id release path with linked path-claim cascade.

Extracted sibling of :mod:`yoke_core.domain.sessions_lifecycle_claim`'s
``release_claim``. Releases a work claim by id and, when the released
claim was process-targeted, cascades the linked non-terminal path
claims through
:func:`yoke_core.domain.sessions_lifecycle_release._release_linked_path_claims`.

The session-scoped release path (`release_target`) already drives the
same cascade helper; this module brings the by-claim-id path to parity
so the function-call surface (``claims.work.release``) and HTTP route
both honor the integration boundary. Audit evidence rides on the
parent ``WorkReleased`` event ``context.linked_path_claim_ids``.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from . import db_backend
from . import sessions_analytics as _sa
from .sessions_analytics import EVENT_WORK_RELEASED, SessionError
from .sessions_claim_lifecycle_lock import lock_session_rows_for_claim_lifecycle
from .sessions_lifecycle_claim_events import emit_steering_released
from .sessions_lifecycle_release_events import (
    build_work_release_post_commit_receipt,
    emit_work_release_post_commit,
)
from .sessions_lifecycle_registry import _get_claim
from .sessions_queries import _now_iso
from .work_claim_targets import (
    TARGET_KIND_EPIC_TASK,
    TARGET_KIND_ITEM,
    TARGET_KIND_STEERING,
    WorkClaimTarget,
    exact_match_clause,
    from_row as work_claim_target_from_row,
)
from .workflow_item_binding_lock import (
    lock_work_claims_workflow_bindings,
    rollback_workflow_binding_write_errors,
)


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


_STEERING_RECEIPT_KEY = "_steering_release"


def find_active_claim(
    conn: Any,
    session_id: str,
    target: WorkClaimTarget,
) -> Optional[Any]:
    """Find the newest active row for an exact typed target."""
    where, target_params = exact_match_clause(conn, target)
    params = (session_id, *target_params)
    return conn.execute(
        "SELECT id FROM work_claims "
        f"WHERE session_id = {_p(conn)} AND {where} AND released_at IS NULL "
        "ORDER BY claimed_at DESC, id DESC LIMIT 1",
        params,
    ).fetchone()


def build_claim_release_post_commit_receipt(
    *,
    session_id: str,
    target: WorkClaimTarget,
    claim_id: int,
    canonical_reason: str,
    reason: str,
    released_at: str,
) -> Dict[str, Any]:
    """Build deferred telemetry for either generic or steering release."""
    if target.kind != TARGET_KIND_STEERING:
        return build_work_release_post_commit_receipt(
            session_id=session_id,
            target=target,
            claim_id=claim_id,
            canonical_reason=canonical_reason,
            reason=reason,
            released_at=released_at,
        )
    return {
        _STEERING_RECEIPT_KEY: True,
        "session_id": session_id,
        "claim_id": claim_id,
        "target": target,
        "reason": reason,
        "reclaimed": canonical_reason == "reclaimed",
    }


def emit_claim_release_post_commit(conn: Any, receipt: Dict[str, Any]) -> None:
    """Emit the target-specific success event after release commit."""
    if receipt.get(_STEERING_RECEIPT_KEY):
        emit_steering_released(
            receipt["session_id"],
            receipt["claim_id"],
            receipt["target"],
            reason=receipt["reason"],
            reclaimed=receipt["reclaimed"],
        )
        return
    emit_work_release_post_commit(conn, receipt)


@rollback_workflow_binding_write_errors
def release_claim_by_id(
    conn: Any,
    claim_id: int,
    reason: str = "released",
) -> Dict[str, Any]:
    """Release ``claim_id`` and cascade linked non-terminal path claims.

    Cascades only when the released claim's ``target_kind == 'process'``
    — item path claims follow the per-item path-claim lifecycle. The
    returned row carries a ``linked_path_claim_ids`` key listing the
    path claims released as part of this call (empty for non-process
    targets or when no linked claims were live).
    """
    from .sessions_lifecycle_release import (
        _canonical_release_reason,
        _release_linked_path_claims,
    )
    from .sessions_render_attribution import release_item_focus_if_current
    from .idea_claim_events import emit_if_idea_release

    now = _now_iso()
    canonical_reason = _canonical_release_reason(reason)

    discovered = conn.execute(
        f"SELECT session_id FROM work_claims WHERE id = {_p(conn)}",
        (claim_id,),
    ).fetchone()
    if discovered is None:
        raise SessionError("NOT_FOUND", f"Claim {claim_id} not found.")
    source_session_id = str(discovered["session_id"] or "")
    if source_session_id:
        lock_session_rows_for_claim_lifecycle(conn, (source_session_id,))

    lock_work_claims_workflow_bindings(conn, (claim_id,))
    row = conn.execute(
        "SELECT session_id, target_kind, scope, released_at "
        f"FROM work_claims WHERE id = {_p(conn)}",
        (claim_id,),
    ).fetchone()
    if row is None:
        raise SessionError("NOT_FOUND", f"Claim {claim_id} not found.")
    if row["released_at"] is not None:
        raise SessionError(
            "ALREADY_RELEASED",
            f"Claim {claim_id} has already been released.",
        )
    target = work_claim_target_from_row(dict(row))

    conn.execute(
        f"UPDATE work_claims SET released_at = {_p(conn)}, "
        f"release_reason = {_p(conn)} WHERE id = {_p(conn)}",
        (now, canonical_reason, claim_id),
    )
    # The caller's release intent is first-class claim state — the
    # released row persists and the frontier defense reads it from here.
    from .claim_chain_state import record_release_intent, touch_epic_task_activity

    record_release_intent(conn, claim_id=claim_id, intent=reason)
    if target.kind == TARGET_KIND_EPIC_TASK:
        touch_epic_task_activity(
            conn,
            epic_id=target.epic_id,
            task_num=target.task_num,
            at=now,
        )

    linked_path_claim_ids: List[int] = []
    if target.kind == "process":
        linked_path_claim_ids = _release_linked_path_claims(
            conn, claim_id, now, canonical_reason
        )

    if target.kind == TARGET_KIND_ITEM:
        release_item_focus_if_current(
            conn,
            str(row["session_id"] or ""),
            target.item_id,
        )

    # Deliberate claim release is real item activity (R1 board-activity
    # semantics); process-target releases are not item-scoped.
    _activity_target = (
        target.item_id
        if target.kind == TARGET_KIND_ITEM
        else (target.epic_id if target.kind == TARGET_KIND_EPIC_TASK else None)
    )
    if _activity_target is not None:
        from yoke_core.domain.item_activity import touch_item_activity

        touch_item_activity(conn, item_id=_activity_target)

    conn.commit()

    item_id_for_event = (
        str(target.item_id)
        if target.kind == TARGET_KIND_ITEM
        else (str(target.epic_id) if target.kind == TARGET_KIND_EPIC_TASK else None)
    )
    task_num_for_event = target.task_num
    context: Dict[str, Any] = {
        "claim_id": claim_id,
        "release_reason": canonical_reason,
        "release_reason_intent": reason,
        "target_kind": row["target_kind"],
    }
    if target.kind == "process":
        context["process_key"] = target.process_key
        context["conflict_group"] = target.conflict_group
        context["linked_path_claim_ids"] = list(linked_path_claim_ids)
    if target.kind == TARGET_KIND_STEERING:
        emit_steering_released(
            str(row["session_id"]),
            claim_id,
            target,
            reason=reason,
            reclaimed=canonical_reason == "reclaimed",
        )
    else:
        _sa._emit_session_event(
            EVENT_WORK_RELEASED,
            session_id=row["session_id"],
            item_id=item_id_for_event,
            task_num=task_num_for_event,
            context=context,
        )

    if target.kind == TARGET_KIND_ITEM:
        emit_if_idea_release(
            conn,
            session_id=str(row["session_id"] or ""),
            target_item_id=int(target.item_id),
            claim_id=int(claim_id),
            release_reason_intent=reason,
            released_at=now,
        )

    claim_row = _get_claim(conn, claim_id)
    if isinstance(claim_row, dict):
        claim_row["linked_path_claim_ids"] = list(linked_path_claim_ids)
    return claim_row


__all__ = [
    "build_claim_release_post_commit_receipt",
    "emit_claim_release_post_commit",
    "find_active_claim",
    "release_claim_by_id",
]
