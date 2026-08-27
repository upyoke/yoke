"""Bulk release of every active claim for a session.

Sibling of :mod:`sessions_lifecycle_release`. The typed per-claim
release path (``release_work_claim_for_execution``) re-focuses
``harness_sessions.current_item_id`` when the released claim's item
matches focus; the by-claim-id sibling (``release_claim_by_id``) was
brought to parity earlier. This bulk path is the third member of the
family: callers ask "release every claim this session holds" without
ending the session (HTTP ``POST /sessions/{id}/release-all``, the legacy
``release-all-claims`` CLI). After such a release no item claim remains,
so the shared focus release degrades to its clear-and-archive shape —
the retained focus would otherwise be structurally stale. The
destructive ``--release-claims`` SessionEnd branch is unaffected —
``end_session`` follows the bulk release with a session-wide clear at
the wrapper layer.
"""

from __future__ import annotations

from typing import Any

from .claim_chain_state import record_release_intent_for_session
from .sessions_claim_lifecycle_lock import lock_session_rows_for_claim_lifecycle
from .sessions_queries import _now_iso
from .sessions_render_attribution import release_current_item_focus
from .workflow_item_binding_lock import (
    lock_work_claims_workflow_bindings,
    rollback_workflow_binding_write_errors,
)
from yoke_core.domain.work_claim_target_sql import LIVENESS_BOUND_SQL


@rollback_workflow_binding_write_errors
def release_all_claims(
    conn: Any,
    session_id: str,
    reason: str = "released",
) -> int:
    """Release a session's liveness-bound claims. Returns count released.

    Sticky kinds survive an explicit session end for the same reason they
    survive the sweep: the resource they hold is still in use.
    """
    now = _now_iso()
    lock_session_rows_for_claim_lifecycle(conn, (session_id,))
    rows = conn.execute(
        "SELECT id FROM work_claims "
        "WHERE session_id = %s AND released_at IS NULL "
        f"AND {LIVENESS_BOUND_SQL} ORDER BY id",
        (session_id,),
    ).fetchall()
    claim_ids = tuple(int(row["id"]) for row in rows)
    lock_work_claims_workflow_bindings(conn, claim_ids)
    released = 0
    for claim_id in claim_ids:
        cursor = conn.execute(
            "UPDATE work_claims SET released_at = %s, release_reason = %s "
            "WHERE id = %s AND released_at IS NULL",
            (now, reason, claim_id),
        )
        released += int(cursor.rowcount)
    record_release_intent_for_session(
        conn,
        session_id=session_id,
        released_at=now,
        intent=reason,
    )
    release_current_item_focus(conn, session_id, commit=False)
    conn.commit()
    return released


__all__ = ["release_all_claims"]
