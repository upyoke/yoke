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
from .sessions_lifecycle_claim_events import emit_steering_scope_released
from .sessions_lifecycle_release_events import (
    build_work_release_post_commit_receipt,
    emit_work_release_post_commit,
)
from .sessions_lifecycle_registry import _get_claim
from .sessions_queries import _now_iso
from .work_claim_targets import (
    TARGET_KIND_EPIC_TASK,
    TARGET_KIND_ITEM,
    TARGET_KIND_STEERING_SCOPE,
    WorkClaimTarget,
    from_row as work_claim_target_from_row,
)
from .workflow_item_binding_lock import (
    lock_work_claims_workflow_bindings,
    rollback_workflow_binding_write_errors,
)


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


_STEERING_SCOPE_RECEIPT_KEY = "_steering_scope_release"


def steering_scope_select_columns(conn: Any, table_alias: str = "") -> str:
    """Return the steering target projection for a work-claim query."""
    prefix = f"{table_alias}." if table_alias else ""
    return ", ".join(
        f"{prefix}{column}"
        for column in ("steering_project_id", "steering_strategy_doc_slugs")
    )


def find_active_claim(
    conn: Any,
    session_id: str,
    target: WorkClaimTarget,
) -> Optional[Any]:
    """Find the newest active row for an exact typed target."""
    if target.kind == TARGET_KIND_ITEM:
        where = f"target_kind='item' AND item_id = {_p(conn)}"
        params = (session_id, target.item_id)
    elif target.kind == TARGET_KIND_EPIC_TASK:
        where = (
            f"target_kind='epic_task' AND epic_id = {_p(conn)} "
            f"AND task_num = {_p(conn)}"
        )
        params = (session_id, target.epic_id, target.task_num)
    elif target.kind == TARGET_KIND_STEERING_SCOPE:
        stored_slugs = target.insert_columns()["steering_strategy_doc_slugs"]
        where = (
            f"target_kind='steering_scope' AND steering_project_id = {_p(conn)} "
            f"AND steering_strategy_doc_slugs = {_p(conn)}"
        )
        params = (session_id, target.steering_project_id, stored_slugs)
    else:
        where = f"target_kind='process' AND process_key = {_p(conn)}"
        params = (session_id, target.process_key)
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
    if target.kind != TARGET_KIND_STEERING_SCOPE:
        return build_work_release_post_commit_receipt(
            session_id=session_id,
            target=target,
            claim_id=claim_id,
            canonical_reason=canonical_reason,
            reason=reason,
            released_at=released_at,
        )
    return {
        _STEERING_SCOPE_RECEIPT_KEY: True,
        "session_id": session_id,
        "claim_id": claim_id,
        "target": target,
        "reason": reason,
        "reclaimed": canonical_reason == "reclaimed",
    }


def emit_claim_release_post_commit(conn: Any, receipt: Dict[str, Any]) -> None:
    """Emit the target-specific success event after release commit."""
    if receipt.get(_STEERING_SCOPE_RECEIPT_KEY):
        emit_steering_scope_released(
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
        _maybe_clear_current_item,
        _release_linked_path_claims,
    )
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
    steering_columns = steering_scope_select_columns(conn)
    row = conn.execute(
        "SELECT session_id, target_kind, item_id, epic_id, task_num, "
        f"process_key, conflict_group, {steering_columns}, released_at "
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

    conn.execute(
        f"UPDATE work_claims SET released_at = {_p(conn)}, "
        f"release_reason = {_p(conn)} WHERE id = {_p(conn)}",
        (now, canonical_reason, claim_id),
    )
    # The caller's release intent is first-class claim state — the
    # released row persists and the frontier defense reads it from here.
    from .claim_chain_state import record_release_intent, touch_epic_task_activity

    record_release_intent(conn, claim_id=claim_id, intent=reason)
    if row["target_kind"] == "epic_task" and row["epic_id"] is not None:
        touch_epic_task_activity(
            conn,
            epic_id=row["epic_id"],
            task_num=row["task_num"],
            at=now,
        )

    linked_path_claim_ids: List[int] = []
    if row["target_kind"] == "process":
        linked_path_claim_ids = _release_linked_path_claims(
            conn, claim_id, now, canonical_reason
        )

    if row["target_kind"] == "item" and row["item_id"] is not None:
        _maybe_clear_current_item(
            conn,
            str(row["session_id"] or ""),
            str(row["item_id"]),
        )

    # Deliberate claim release is real item activity (R1 board-activity
    # semantics); process-target releases are not item-scoped.
    _activity_target = (
        row["item_id"]
        if row["target_kind"] == "item"
        else (row["epic_id"] if row["target_kind"] == "epic_task" else None)
    )
    if _activity_target is not None:
        from yoke_core.domain.item_activity import touch_item_activity

        touch_item_activity(conn, item_id=_activity_target)

    conn.commit()

    item_id_for_event = (
        str(row["item_id"])
        if row["target_kind"] == "item" and row["item_id"] is not None
        else (str(row["epic_id"]) if row["target_kind"] == "epic_task" else None)
    )
    task_num_for_event = row["task_num"] if row["target_kind"] == "epic_task" else None
    context: Dict[str, Any] = {
        "claim_id": claim_id,
        "release_reason": canonical_reason,
        "release_reason_intent": reason,
        "target_kind": row["target_kind"],
    }
    if row["target_kind"] == "process":
        context["process_key"] = row["process_key"]
        context["conflict_group"] = row["conflict_group"]
        context["linked_path_claim_ids"] = list(linked_path_claim_ids)
    if row["target_kind"] == TARGET_KIND_STEERING_SCOPE:
        emit_steering_scope_released(
            str(row["session_id"]),
            claim_id,
            work_claim_target_from_row(dict(row)),
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

    if row["target_kind"] == "item" and row["item_id"] is not None:
        emit_if_idea_release(
            conn,
            session_id=str(row["session_id"] or ""),
            target_item_id=int(row["item_id"]),
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
    "steering_scope_select_columns",
]
