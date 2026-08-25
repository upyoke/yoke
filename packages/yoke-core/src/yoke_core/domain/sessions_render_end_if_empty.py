"""Idle-session cleanup that preserves claim and chain continuity."""

from __future__ import annotations

from typing import Any, Dict

from . import sessions_analytics as _sa
from .sessions_analytics import EVENT_HARNESS_SESSION_ENDED
from .sessions_claim_lifecycle_lock import lock_session_rows_for_claim_lifecycle
from .sessions_lifecycle_registry import _get_session
from .sessions_queries import _now_iso
from .sessions_render_attribution import clear_current_item
from .sessions_render_end_chain_pending import (
    chain_pending_state,
    last_released_at,
    next_action_command,
    next_offer_step,
)
from .workflow_item_binding_lock import rollback_workflow_binding_write_errors


def _document_lock_count(conn: Any, session_id: str) -> int:
    """Count the strategy documents this session still holds directly."""
    from .schema_common import _table_exists

    if not _table_exists(conn, "strategy_doc_claims"):
        return 0
    row = conn.execute(
        """SELECT COUNT(*) AS cnt
           FROM strategy_doc_claims
           WHERE owner_kind = 'session' AND owner_session_id = %s
             AND released_at IS NULL""",
        (session_id,),
    ).fetchone()
    return int(row["cnt"] or 0)


@rollback_workflow_binding_write_errors
def end_session_if_empty(
    conn: Any,
    session_id: str,
    *,
    triggered_by: str = "stop-hook",
) -> Dict[str, Any]:
    """End a session only when it holds nothing and has no chain budget left.

    A session-owned strategy-document lock counts as holding something: the
    non-destructive path never releases what a session holds, and a transient
    end would otherwise drop a coordinator's document lock on a laptop sleep.
    """
    session_rows = lock_session_rows_for_claim_lifecycle(conn, (session_id,))
    if session_id not in session_rows:
        conn.commit()
        return {
            "session_id": session_id,
            "status": "not_found",
            "ended": False,
            "active_claim_count": 0,
        }
    if session_rows[session_id] is not None:
        conn.commit()
        return {
            "session_id": session_id,
            "status": "already_ended",
            "ended": False,
            "active_claim_count": 0,
        }

    claim_count = conn.execute(
        """SELECT COUNT(*) AS cnt
           FROM work_claims
           WHERE session_id = %s AND released_at IS NULL""",
        (session_id,),
    ).fetchone()["cnt"]
    if claim_count:
        conn.commit()
        return {
            "session_id": session_id,
            "status": "has_claims",
            "ended": False,
            "active_claim_count": int(claim_count),
        }

    lock_count = _document_lock_count(conn, session_id)
    if lock_count:
        conn.commit()
        return {
            "session_id": session_id,
            "status": "has_document_locks",
            "ended": False,
            "active_claim_count": 0,
            "active_document_lock_count": int(lock_count),
        }

    state = chain_pending_state(conn, session_id)
    if state.pending:
        from .scheduler_events import emit_chain_end_deferred

        last_release_at = last_released_at(conn, session_id)
        next_action = next_action_command(
            conn,
            session_id,
            next_offer_step(state),
        )
        result = {
            "session_id": session_id,
            "status": "chain_pending",
            "ended": False,
            "active_claim_count": 0,
            "checkpoint_step": state.step,
            "max_chain_steps": state.max_chain_steps,
            "handler_outcome": state.handler_outcome,
            "chainable": state.chainable,
            "action": state.action,
            "item_id": state.item_id,
            "last_release_at": last_release_at,
            "triggered_by": triggered_by,
            "next_action": next_action,
        }
        conn.commit()
        emit_chain_end_deferred(
            session_id=session_id,
            triggered_by=triggered_by,
            checkpoint_step=state.step,
            max_chain_steps=state.max_chain_steps,
            handler_outcome=state.handler_outcome,
            chainable=state.chainable,
            action=state.action,
            item_id=state.item_id,
            last_release_at=last_release_at,
        )
        return result

    clear_current_item(conn, session_id, commit=False)
    conn.execute(
        "UPDATE harness_sessions SET ended_at = %s WHERE session_id = %s",
        (_now_iso(), session_id),
    )
    conn.commit()
    _sa._emit_session_event(
        EVENT_HARNESS_SESSION_ENDED,
        session_id=session_id,
        context={"reason": "session_empty_auto_ended"},
    )
    return {
        "session_id": session_id,
        "status": "ended",
        "ended": True,
        "active_claim_count": 0,
        "session": _get_session(conn, session_id),
    }


__all__ = ["end_session_if_empty"]
