"""Cancel a session launch, ending the session it started only before work."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from yoke_contracts.session_control.liveness import ended_session_sql
from yoke_contracts.timestamps import parse_instant

from yoke_core.domain import json_helper
from yoke_core.domain.session_launch_store import (
    begin_mutation,
    get_launch,
    marker,
    update_launch,
    utc_now,
)
from yoke_core.domain.session_launch_types import (
    LaunchAuthorization,
    LaunchRecord,
    SessionLaunchError,
)
from yoke_core.domain.session_launch_visibility import launch_visibility
from yoke_core.domain.session_termination import terminate_cancelled_launch_session
from yoke_core.domain.sessions_analytics import SessionError

#: The launched session already holds its instructions and may be working.
SESSION_WORKING_CODE = "launch_session_working"


def cancel_launch(
    conn: Any,
    *,
    launch_id: str,
    auth: LaunchAuthorization,
    now: datetime | str | None = None,
) -> LaunchRecord:
    """Stop a launch; a registered session that has done no work ends with it.

    A native process that exists but never registered stays for
    reconciliation, and a cancelled launch is never revived.
    """
    current = utc_now() if now is None else parse_instant(now)
    begin_mutation(conn)
    try:
        launch = get_launch(conn, launch_id, for_update=True)
        if (
            auth.actor_id != launch.requester_actor_id
            and not auth.can_administer_project
        ):
            raise SessionLaunchError(
                "permission_denied",
                "only the requester or project admin may cancel",
            )
        if launch.state == "cancelled":
            conn.commit()
            return launch
        delivery = launch_visibility(
            state=launch.state,
            result_code=launch.result_code,
            native_session_id=launch.native_session_id,
            registered_session_id=launch.registered_session_id,
        )["instruction_delivery"]
        if delivery == "delivered":
            ended = conn.execute(
                f"SELECT 1 FROM harness_sessions s WHERE s.session_id = {marker(conn)} "
                f"AND {ended_session_sql('s')}",
                (launch.registered_session_id,),
            ).fetchone()
            if ended is None:
                raise _working_refusal(launch)
            result = update_launch(
                conn,
                launch_id,
                state="cancelled",
                completed_at=current,
                result_code="cancelled_session_ended",
            )
            conn.commit()
            return result
        if launch.registered_session_id:
            result = _end_unworked_session(conn, launch, auth=auth, now=current)
        elif launch.state == "failed" and json_helper.loads_text(
            launch.result_evidence or "{}"
        ).get("native_exit_at"):
            result = update_launch(
                conn,
                launch_id,
                state="cancelled",
                completed_at=current,
                result_code="cancelled",
            )
        elif launch.native_session_id or launch.state in {
            "launching",
            "outcome_unknown",
        }:
            result = update_launch(
                conn,
                launch_id,
                delivery_changed_at=current,
                state="outcome_unknown",
                result_code="cancellation_requires_reconciliation",
            )
        else:
            result = update_launch(
                conn,
                launch_id,
                state="cancelled",
                completed_at=current,
                result_code="cancelled",
            )
        conn.commit()
        return result
    except Exception:
        conn.rollback()
        raise


def _end_unworked_session(
    conn: Any, launch: LaunchRecord, *, auth: LaunchAuthorization, now: datetime
) -> LaunchRecord:
    session_id = str(launch.registered_session_id)
    try:
        terminate_cancelled_launch_session(
            conn,
            target_session_id=session_id,
            actor_id=auth.actor_id,
            caller_session_id=auth.session_id,
            reason=f"launch {launch.launch_id} cancelled before its instructions were delivered",
        )
    except SessionError as exc:
        raise SessionLaunchError(
            "launch_session_termination_refused",
            f"launch {launch.launch_id} was not cancelled: ending its session "
            f"{session_id} was refused ({exc.code}): {exc.message}",
            launch_state=launch.state,
        ) from exc
    return update_launch(
        conn,
        launch.launch_id,
        state="cancelled",
        completed_at=now,
        result_code="cancelled_session_ended",
    )


def _working_refusal(launch: LaunchRecord) -> SessionLaunchError:
    session_id = launch.registered_session_id or launch.native_session_id or "SESSION"
    return SessionLaunchError(
        SESSION_WORKING_CODE,
        f"launch {launch.launch_id} delivered its instructions to session "
        f"{session_id}, which is already working; cancel does not stop it. "
        f"To end that session deliberately: yoke sessions terminate "
        f'{session_id} --reason "<why>"',
        launch_state=launch.state,
    )


__all__ = ["SESSION_WORKING_CODE", "cancel_launch"]
