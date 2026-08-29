"""Claim cleanup for an item that finished.

When an item completes, claims other sessions still hold on it are
foreign leftovers — a stale offer session that never engaged, a lane
that outlived its work. Releasing them frees the item; releasing the
focus of the sessions that held them keeps the roster from rendering a
finished item as the work those sessions are on.
"""

from __future__ import annotations

from typing import Any, List

from . import sessions_analytics as _sa
from .sessions_analytics import EVENT_WORK_RELEASED
from .sessions_item_focus_release import release_item_focus_for_sessions
from .sessions_queries import _now_iso, normalize_claim_item_id
from .work_claim_targets import (
    from_row as work_claim_target_from_row,
    scope_int_sql,
)
from .workflow_item_binding_lock import (
    lock_item_workflow_bindings,
    rollback_workflow_binding_write_errors,
)


@rollback_workflow_binding_write_errors
def release_claims_for_done_item(
    conn: Any,
    item_id: str,
) -> int:
    """Release all unreleased claims on an item that has transitioned to done.

    When an item completes in any session, foreign claims from other sessions
    (e.g., stale offer sessions that never engaged) must be cleaned up.
    Claims reuse the existing ``completed`` release_reason vocabulary to avoid
    expanding the schema enum; the item-done cause remains queryable via
    per-claim ``WorkReleased`` event context.

    Returns the number of claims released.
    """
    now = _now_iso()
    normalized = normalize_claim_item_id(item_id)
    if not normalized.isdigit():
        return 0
    item_id_int = int(normalized)
    lock_item_workflow_bindings(conn, (item_id_int,))

    item_scope = scope_int_sql(conn, "wc.scope", "item_id")
    unreleased = conn.execute(
        f"""SELECT wc.id, wc.session_id, wc.target_kind, wc.scope
           FROM work_claims wc
           WHERE wc.target_kind='item' AND {item_scope} = %s
             AND wc.released_at IS NULL""",
        (item_id_int,),
    ).fetchall()

    released = 0
    holder_session_ids: List[str] = []
    for claim_row in unreleased:
        target = work_claim_target_from_row(dict(claim_row))
        holder_session_ids.append(str(claim_row["session_id"]))
        conn.execute(
            "UPDATE work_claims SET released_at = %s, release_reason = 'completed' WHERE id = %s",
            (now, claim_row["id"]),
        )
        released += 1

        _sa._emit_session_event(
            EVENT_WORK_RELEASED,
            session_id=claim_row["session_id"],
            item_id=str(target.item_id),
            task_num=None,
            context={
                "claim_id": claim_row["id"],
                "release_reason": "completed",
                "cleanup_reason": "item_done",
            },
        )

    conn.commit()
    release_item_focus_for_sessions(conn, item_id_int, holder_session_ids)
    return released


__all__ = ["release_claims_for_done_item"]
