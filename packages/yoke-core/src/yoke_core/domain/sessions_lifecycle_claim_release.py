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

from typing import Any, Dict, List

from . import db_backend
from . import sessions_analytics as _sa
from .sessions_analytics import EVENT_WORK_RELEASED, SessionError
from .sessions_lifecycle_registry import _get_claim
from .sessions_queries import _now_iso


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


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

    row = conn.execute(
        "SELECT session_id, target_kind, item_id, epic_id, task_num, "
        "process_key, conflict_group, released_at "
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
            conn, epic_id=row["epic_id"], task_num=row["task_num"], at=now,
        )

    linked_path_claim_ids: List[int] = []
    if row["target_kind"] == "process":
        linked_path_claim_ids = _release_linked_path_claims(
            conn, claim_id, now, canonical_reason
        )

    if row["target_kind"] == "item" and row["item_id"] is not None:
        _maybe_clear_current_item(
            conn, str(row["session_id"] or ""), str(row["item_id"]),
        )

    # Deliberate claim release is real item activity (R1 board-activity
    # semantics); process-target releases are not item-scoped.
    _activity_target = (
        row["item_id"] if row["target_kind"] == "item" else
        (row["epic_id"] if row["target_kind"] == "epic_task" else None)
    )
    if _activity_target is not None:
        from yoke_core.domain.item_activity import touch_item_activity
        touch_item_activity(conn, item_id=_activity_target)

    conn.commit()

    item_id_for_event = (
        str(row["item_id"]) if row["target_kind"] == "item" and row["item_id"] is not None
        else (str(row["epic_id"]) if row["target_kind"] == "epic_task" else None)
    )
    task_num_for_event = (
        row["task_num"] if row["target_kind"] == "epic_task" else None
    )
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


__all__ = ["release_claim_by_id"]
