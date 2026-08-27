"""Permanent session termination and atomic message silencing."""

from __future__ import annotations

from typing import Any

from yoke_core.domain import db_backend
from yoke_core.domain.session_operator_authority import (
    require_operator_or_steering_authority,
    session_control_target,
)
from yoke_core.domain.session_termination_events import emit_session_terminated
from yoke_core.domain.sessions_analytics import SessionError
from yoke_core.domain.sessions_queries import _now_iso
from yoke_core.domain.sessions_render_end import end_session


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _cancel_open_recipients(conn: Any, session_id: str, now: str) -> int:
    marker = _p(conn)
    row = conn.execute(
        "SELECT COUNT(*) FROM session_message_recipients "
        f"WHERE session_id = {marker} AND state IN ('pending','injected')",
        (session_id,),
    ).fetchone()
    count = int(row[0]) if row is not None else 0
    conn.execute(
        "UPDATE session_message_recipients SET state='cancelled',cancelled_at="
        + marker
        + ",injection_lease_id=NULL,injection_leased_at=NULL,"
        "injection_lease_expires_at=NULL WHERE session_id="
        + marker
        + " AND state IN ('pending','injected')",
        (now, session_id),
    )
    conn.execute(
        "UPDATE session_message_attempts SET completed_at="
        + marker
        + ",result_code='session_terminated' WHERE target_session_id="
        + marker
        + " AND completed_at IS NULL",
        (now, session_id),
    )
    return count


def _launch_identity(conn: Any, session_id: str) -> tuple[str | None, str | None]:
    row = conn.execute(
        "SELECT launch_id,native_session_id FROM session_launches "
        f"WHERE registered_session_id={_p(conn)} "
        "ORDER BY completed_at DESC,created_at DESC LIMIT 1",
        (session_id,),
    ).fetchone()
    if row is None:
        return None, None
    return str(row[0]), str(row[1] or "") or None


def _queue_reap(
    conn: Any,
    *,
    target: dict[str, Any],
    requested_at: str,
) -> str:
    launch_id, launch_native_id = _launch_identity(conn, str(target["session_id"]))
    machine_id = str(target.get("machine_id") or "") or None
    native_id = str(target.get("native_thread_id") or "") or launch_native_id
    state = "pending" if machine_id else "unavailable"
    marker = _p(conn)
    values = (
        str(target["session_id"]),
        int(target["project_id"]),
        machine_id,
        str(target.get("executor_surface") or "") or None,
        native_id,
        launch_id,
        state,
        requested_at,
    )
    conn.execute(
        "INSERT INTO session_termination_reaps "
        "(target_session_id,project_id,machine_id,executor_surface,"
        "target_native_thread_id,launch_id,state,requested_at) VALUES ("
        + ",".join(marker for _ in values)
        + ") ON CONFLICT(target_session_id) DO UPDATE SET "
        "project_id=excluded.project_id,machine_id=excluded.machine_id,"
        "executor_surface=excluded.executor_surface,"
        "target_native_thread_id=excluded.target_native_thread_id,"
        "launch_id=excluded.launch_id,state=excluded.state,"
        "requested_at=excluded.requested_at,lease_id=NULL,lease_expires_at=NULL,"
        "completed_at=NULL,result_code=NULL,evidence=NULL",
        values,
    )
    return state


def terminate_session(
    conn: Any,
    *,
    target_session_id: str,
    actor_id: int,
    caller_session_id: str,
    reason: str,
    override_chain_end: bool = False,
    chain_end_rationale: str | None = None,
) -> dict[str, Any]:
    """End, silence, and permanently make one session non-wakeable."""
    termination_reason = reason.strip()
    if not termination_reason:
        raise SessionError("TERMINATION_REASON_REQUIRED", "Termination reason is required.")
    target = session_control_target(conn, target_session_id)
    authority = require_operator_or_steering_authority(
        conn,
        actor_id=actor_id,
        caller_session_id=caller_session_id,
        project_id=int(target["project_id"]),
        action="Session termination",
        error_code="TERMINATION_AUTHORITY_REQUIRED",
    )
    if target.get("terminated_at"):
        reap = conn.execute(
            f"SELECT state FROM session_termination_reaps WHERE target_session_id="
            f"{_p(conn)}",
            (target_session_id,),
        ).fetchone()
        return {
            "session": target,
            "cancelled_recipient_count": 0,
            "reap_state": str(reap[0]) if reap is not None else "unavailable",
            "deduplicated": True,
        }

    now = _now_iso()
    marker = _p(conn)
    conn.execute(
        "UPDATE harness_sessions SET terminated_at="
        + marker
        + ",terminated_by_actor_id="
        + marker
        + ",terminated_by_session_id="
        + marker
        + ",termination_reason="
        + marker
        + f" WHERE session_id={marker}",
        (now, int(actor_id), caller_session_id, termination_reason, target_session_id),
    )
    cancelled = _cancel_open_recipients(conn, target_session_id, now)
    reap_state = _queue_reap(conn, target=target, requested_at=now)
    was_ended = target.get("ended_at") is not None
    if was_ended:
        conn.execute(
            f"UPDATE harness_sessions SET ended_at=NULL WHERE session_id={marker}",
            (target_session_id,),
        )
    session = end_session(
        conn,
        target_session_id,
        force=True,
        release_claims=True,
        override_chain_end=override_chain_end,
        chain_end_rationale=chain_end_rationale,
    )
    chain_override_authorized = bool(
        override_chain_end and str(chain_end_rationale or "").strip()
    )
    emit_session_terminated(
        target_session_id,
        context={
            "terminated_by_actor_id": int(actor_id),
            "terminated_by_session_id": caller_session_id,
            "authority": authority,
            "reason": termination_reason,
            "cancelled_recipient_count": cancelled,
            "reap_state": reap_state,
            "was_ended": was_ended,
            "chain_override_authorized": chain_override_authorized,
        },
    )
    return {
        "session": session,
        "cancelled_recipient_count": cancelled,
        "reap_state": reap_state,
        "deduplicated": False,
    }


__all__ = ["terminate_session"]
