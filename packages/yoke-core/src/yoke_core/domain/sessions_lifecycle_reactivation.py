"""Conditional auto-reacquire on session reactivation.

Called from sessions_lifecycle_registry.register_session after the
``ended_at=NULL`` reactivation UPDATE commits. Two outputs:

* the existing ``SessionReactivatedWithReleasedClaims`` advisory
  records *what* prior claims the reactivation surfaced.
* the new conditional auto-reacquire path re-inserts active
  ``work_claims`` rows for the reactivating session when (a) the prior
  release happened with ``release_reason='session_ended'`` inside
  ``session_reactivation_reacquire_window_s``, AND (b) no other
  session currently holds an active claim on the same target.

A receipt event ``SessionReactivationReacquiredClaims`` records the
auto-reacquire outcome (with per-target reacquired vs. conflict).
Honors the conflict semantics — when another session
legitimately holds the item, reacquire falls through to advisory
only and the operator must coordinate or move on.

``HarnessSessionResumed`` is emitted on EVERY reactivation, claims or
not: it marks the episode boundary, and a session that was claim-free
when the transient end closed it crossed that boundary exactly like a
claim-holding one. Only the claim-shaped outputs (the advisory, the
reacquire receipt, the operator-facing resume notice) stay conditional
on there being claims to describe.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .sessions_analytics_core import (
    EVENT_SESSION_REACTIVATED_WITH_RELEASED_CLAIMS,
    _emit_session_event,
)
from .sessions_analytics import SessionError
from .sessions_claim_lifecycle_lock import lock_session_rows_for_claim_lifecycle
from .sessions_lifecycle_reactivation_claims import (
    DEFAULT_REACQUIRE_WINDOW_S,
    auto_reacquire_session_ended_claims,
    target_descriptor,
)
from .sessions_resume_notice import write_pending_resume_notice
from .workflow_item_binding_lock import rollback_workflow_binding_write_errors


@rollback_workflow_binding_write_errors
def emit_reactivated_with_released_claims(
    conn: Any,
    session_id: str,
    *,
    reacquire_window_s: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """Emit the advisory event AND drive conditional auto-reacquire.

    Returns the list of prior released-claim descriptors. The advisory
    is preserved verbatim for doctrine continuity; the new
    auto-reacquire receipt event is emitted in addition when at least
    one claim was reacquired OR at least one conflict was observed.
    """
    session_rows = lock_session_rows_for_claim_lifecycle(conn, (session_id,))
    if session_id not in session_rows:
        raise SessionError("NOT_FOUND", f"Session '{session_id}' not found.")
    if session_rows[session_id] is not None:
        raise SessionError(
            "SESSION_ENDED",
            f"Session '{session_id}' has already ended.",
        )

    rows = conn.execute(
        "SELECT id, target_kind, item_id, epic_id, task_num, "
        "process_key, conflict_group "
        "FROM work_claims "
        "WHERE session_id = %s AND release_reason = 'session_ended' "
        "  AND released_at IS NOT NULL "
        "ORDER BY id DESC",
        (session_id,),
    ).fetchall()

    from .sessions_lifecycle_resumption_emit import emit_session_resumed

    if not rows:
        conn.commit()
        # A claim-free session still crossed an episode boundary — the
        # transient end simply had no claims to release. Mark the resumption
        # so audit finds it with one event_name predicate. The operator-facing
        # resume notice stays unwritten: with no prior claims its block would
        # have nothing to name.
        emit_session_resumed(
            session_id=session_id,
            released_claims=[],
            reacquired_claims=[],
            conflicts=[],
        )
        return []

    released_claims: List[Dict[str, Any]] = [target_descriptor(r) for r in rows]
    reacquired, conflicts = auto_reacquire_session_ended_claims(
        conn,
        session_id,
        reacquire_window_s=reacquire_window_s,
        commit=False,
    )

    # The claims and render-once resume notice are one state transition.
    # A notice write failure rolls back every reacquired claim.
    write_pending_resume_notice(
        conn,
        session_id,
        released_claims=released_claims,
        reacquired_count=len(reacquired),
        conflict_count=len(conflicts),
        commit=False,
    )
    conn.commit()

    _emit_session_event(
        EVENT_SESSION_REACTIVATED_WITH_RELEASED_CLAIMS,
        session_id=session_id,
        context={
            "released_claim_count": len(released_claims),
            "released_claims": released_claims,
        },
    )
    if reacquired or conflicts:
        from .scheduler_events import emit_session_reactivation_reacquired_claims

        emit_session_reactivation_reacquired_claims(
            session_id=session_id,
            reacquired_count=len(reacquired),
            conflict_count=len(conflicts),
            claim_details=[
                *({"outcome": "reacquired", **r} for r in reacquired),
                *({"outcome": "conflict", **c} for c in conflicts),
            ],
        )

    emit_session_resumed(
        session_id=session_id,
        released_claims=released_claims,
        reacquired_claims=reacquired,
        conflicts=conflicts,
    )

    return released_claims


__all__ = [
    "DEFAULT_REACQUIRE_WINDOW_S",
    "auto_reacquire_session_ended_claims",
    "emit_reactivated_with_released_claims",
]
