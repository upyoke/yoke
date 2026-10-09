"""Permanent session termination and atomic message silencing."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from yoke_contracts.timestamps import format_instant

from yoke_core.domain import db_backend
from yoke_core.domain.session_message_store import cancel_open_recipients
from yoke_core.domain.session_message_types import utc_now
from yoke_core.domain.db_helpers import instant_parameter
from yoke_core.domain.session_resume_in_flight import resume_in_flight
from yoke_core.domain.session_operator_authority import (
    require_operator_or_steering_authority,
    session_control_target,
)
from yoke_core.domain.session_termination_events import emit_session_terminated
from yoke_core.domain.sessions_analytics import SessionError
from yoke_core.domain.sessions_render_end import end_session


#: Recorded on a delivery attempt closed by deliberate termination.
TERMINATED_RESULT_CODE = "session_terminated"

#: Termination refused because a resume already answered the recorded exit.
RESUME_IN_FLIGHT_CODE = "TERMINATION_RESUME_IN_FLIGHT"

#: The CLI flag that terminates through an in-flight resume on purpose.
RESUME_OVERRIDE_FLAG = "--allow-resume-in-flight"


def _refuse_resuming_session(conn: Any, target: dict[str, Any]) -> None:
    """Refuse to kill a worker a wake is already bringing back.

    A headless worker's native exits between turns; the next message
    resumes it from its transcript. The recorded exit stays on the row until
    that resumed process stamps activity, so in that window the worker reads
    as dead while it is starting. Terminating it then destroys a live worker.
    """
    session_id = str(target["session_id"])
    resume = resume_in_flight(conn, session_id, now=utc_now())
    if resume is None:
        return
    exited = target.get("native_process_gone_at")
    after = (
        f" after its recorded native exit at {format_instant(exited)}"
        if exited is not None
        else ""
    )
    raise SessionError(
        RESUME_IN_FLIGHT_CODE,
        f"Session {session_id} is resuming, not dead: {resume.describe()}"
        f"{after}. A headless worker's process exits between turns and the "
        "next message resumes it from its transcript. Message it instead "
        f"(`yoke say --session {session_id} --stdin`). Terminate only with "
        "evidence it cannot resume, or to restaff it deliberately, by "
        f"re-running with {RESUME_OVERRIDE_FLAG}.",
    )


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _launch_identity(conn: Any, session_id: str) -> tuple[str | None, str | None]:
    """Find the launch that started this session by either identity column.

    A session is named on its launch twice, and the two are written by
    different events: the relay records ``native_session_id`` when it reads
    the native's identity, and registration records
    ``registered_session_id`` when the attested session binds. Either can be
    absent while the session itself runs normally, so matching on only one
    of them loses the launch for exactly the sessions a reap most needs it
    for. Without it the reap carries no launch custody handle and no native
    id, and reports ``not_found`` for a native that is still running.
    """
    marker = _p(conn)
    row = conn.execute(
        "SELECT launch_id,native_session_id FROM session_launches "
        f"WHERE registered_session_id={marker} OR native_session_id={marker} "
        "ORDER BY completed_at DESC,created_at DESC LIMIT 1",
        (session_id, session_id),
    ).fetchone()
    if row is None:
        return None, None
    return str(row[0]), str(row[1] or "") or None


def _queue_reap(
    conn: Any,
    *,
    target: dict[str, Any],
    requested_at: datetime,
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
        instant_parameter(conn, requested_at),
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
    allow_resume_in_flight: bool = False,
) -> dict[str, Any]:
    """End, silence, and permanently make one session non-wakeable.

    A session a wake is resuming is refused unless ``allow_resume_in_flight``
    says the caller means to kill it anyway.
    """
    termination_reason = reason.strip()
    if not termination_reason:
        raise SessionError(
            "TERMINATION_REASON_REQUIRED", "Termination reason is required."
        )
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

    if not allow_resume_in_flight:
        _refuse_resuming_session(conn, target)

    now = utc_now()
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
        (
            instant_parameter(conn, now),
            int(actor_id),
            caller_session_id,
            termination_reason,
            target_session_id,
        ),
    )
    cancelled = cancel_open_recipients(
        conn,
        session_id=target_session_id,
        cancelled_at=now,
        result_code=TERMINATED_RESULT_CODE,
    )
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
            "allow_resume_in_flight": allow_resume_in_flight,
        },
    )
    return {
        "session": session,
        "cancelled_recipient_count": cancelled,
        "reap_state": reap_state,
        "deduplicated": False,
    }


__all__ = [
    "RESUME_IN_FLIGHT_CODE",
    "RESUME_OVERRIDE_FLAG",
    "terminate_session",
]
