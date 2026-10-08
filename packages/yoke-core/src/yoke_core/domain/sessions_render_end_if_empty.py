"""Idle-session cleanup that preserves holdings and pending delivery."""

from __future__ import annotations

from datetime import timedelta
from typing import Any, Dict, Sequence

from . import sessions_analytics as _sa
from .session_launch_abandonment import settle_and_notify
from .sessions_analytics import EVENT_HARNESS_SESSION_ENDED
from .sessions_claim_lifecycle_lock import lock_session_rows_for_claim_lifecycle
from .sessions_lifecycle_registry import _get_session
from .session_message_types import parse_timestamp, row_dict, timestamp, utc_now
from .sessions_queries import _now_iso
from .sessions_render_attribution import clear_current_item
from .session_keepalive import session_keepalive_holds
from .session_launch_pending_delivery import pending_launch_deliveries
from .workflow_item_binding_lock import rollback_workflow_binding_write_errors
from yoke_contracts.fleet_policy import WAKE_ACK_GRACE_SECONDS
from yoke_core.domain.work_claim_target_sql import LIVENESS_BOUND_SQL


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


def _wake_ack_grace_seconds(conn: Any, project_id: Any) -> int:
    """Return the product acknowledgement grace period."""
    return WAKE_ACK_GRACE_SECONDS


def wake_deliveries_in_flight(
    conn: Any, session_ids: Sequence[str]
) -> Dict[str, Dict[str, Any]]:
    """Name, per session, a message whose wake is still inside its window.

    Batched so the roster projection can show the same blocker the end path
    enforces without asking once per session. The two must agree: an
    operator reading "nothing blocking" while the hook refuses to end is how
    a real refusal becomes invisible.

    A wake exists to start a turn that takes delivery, and the turn is not
    delivery: the envelope arrives through a hook that fires inside it. So
    between the wake landing and the envelope being acknowledged there is a
    window where the session legitimately holds nothing yet - no claim, no
    lock, no chain - and ending it there reaps the very turn the wake paid
    for. Every later wake then finds an ended session and repeats the loop,
    which is what a cursor-cli acceptance cell recorded three times over.

    The window is the same ``wake_ack_grace_seconds`` that message and manual
    wake recovery use before treating a hook or wake delivery as stalled;
    rating both sides on the same clock is what keeps them agreeing.
    """
    from .db_optional_queries import fetch_optional_rows

    targets = tuple(str(one) for one in session_ids if str(one or "").strip())
    if not targets:
        return {}
    now = utc_now()
    rows = fetch_optional_rows(
        conn,
        """SELECT r.session_id, r.message_id, r.project_id, r.state, r.last_wake_at
           FROM session_message_recipients r
           JOIN session_messages m ON m.message_id = r.message_id
           WHERE r.session_id IN ("""
        + ",".join("%s" for _ in targets)
        + """)
             AND r.state IN ('pending','injected')
             AND r.last_wake_at IS NOT NULL
             AND m.cancelled_at IS NULL
             AND m.expires_at > %s
           ORDER BY r.last_wake_at DESC""",
        (*targets, timestamp(now)),
        savepoint="_yoke_wake_delivery_probe",
    )
    in_flight: Dict[str, Dict[str, Any]] = {}
    for raw in rows:
        row = row_dict(raw)
        session_id = str(row["session_id"])
        if session_id in in_flight:
            continue
        last_wake_at = parse_timestamp(row.get("last_wake_at"))
        if last_wake_at is None:
            continue
        grace = timedelta(seconds=_wake_ack_grace_seconds(conn, row["project_id"]))
        if last_wake_at + grace <= now:
            continue
        in_flight[session_id] = {
            "status": "wake_delivery_in_flight",
            "active_claim_count": 0,
            "message_id": str(row["message_id"]),
            "recipient_state": str(row["state"]),
            "wake_delivery_window_ends_at": timestamp(last_wake_at + grace),
        }
    return in_flight


def end_session_blocker_facts(
    *,
    active_claim_count: int = 0,
    active_document_lock_count: int = 0,
    keepalive: Dict[str, Any] | None = None,
    launch_delivery: Dict[str, Any] | None = None,
    wake_delivery: Dict[str, Any] | None = None,
) -> Dict[str, Any] | None:
    """Return the structured reason an otherwise-live session cannot end."""
    if active_claim_count:
        return {
            "status": "has_claims",
            "active_claim_count": int(active_claim_count),
        }
    if active_document_lock_count:
        return {
            "status": "has_document_locks",
            "active_claim_count": 0,
            "active_document_lock_count": int(active_document_lock_count),
        }
    if keepalive is not None:
        return {
            "status": "keepalive_held",
            "active_claim_count": 0,
            **keepalive,
        }
    if launch_delivery is not None:
        return dict(launch_delivery)
    if wake_delivery is not None:
        return dict(wake_delivery)
    return None


@rollback_workflow_binding_write_errors
def end_session_if_empty(
    conn: Any,
    session_id: str,
    *,
    triggered_by: str = "stop-hook",
) -> Dict[str, Any]:
    """End a session only when it holds nothing and has no pending delivery.

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
        f"""SELECT COUNT(*) AS cnt
           FROM work_claims
           WHERE session_id = %s AND released_at IS NULL
             AND {LIVENESS_BOUND_SQL}""",
        (session_id,),
    ).fetchone()["cnt"]
    if claim_count:
        conn.commit()
        return {
            "session_id": session_id,
            "ended": False,
            **end_session_blocker_facts(active_claim_count=int(claim_count)),
        }

    lock_count = _document_lock_count(conn, session_id)
    if lock_count:
        conn.commit()
        return {
            "session_id": session_id,
            "ended": False,
            **end_session_blocker_facts(
                active_document_lock_count=int(lock_count),
            ),
        }

    keepalive = session_keepalive_holds(conn, (session_id,)).get(session_id)
    if keepalive is not None:
        conn.commit()
        return {
            "session_id": session_id,
            "ended": False,
            **end_session_blocker_facts(keepalive=keepalive),
        }

    launch_delivery = pending_launch_deliveries(conn, (session_id,)).get(session_id)
    if launch_delivery is not None:
        conn.commit()
        return {
            "session_id": session_id,
            "ended": False,
            **end_session_blocker_facts(launch_delivery=launch_delivery),
        }

    wake_delivery = wake_deliveries_in_flight(conn, (session_id,)).get(session_id)
    if wake_delivery is not None:
        conn.commit()
        return {
            "session_id": session_id,
            "ended": False,
            **end_session_blocker_facts(wake_delivery=wake_delivery),
        }

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
    settle_and_notify(conn, session_id, end_reason="session_empty_auto_ended")
    return {
        "session_id": session_id,
        "status": "ended",
        "ended": True,
        "active_claim_count": 0,
        "session": _get_session(conn, session_id),
    }


__all__ = [
    "end_session_blocker_facts",
    "end_session_if_empty",
    "wake_deliveries_in_flight",
]
