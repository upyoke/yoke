"""Record a running watch wrapper's pulse in the existing activity owner."""

from datetime import datetime

from pydantic import BaseModel
from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)
from yoke_contracts.refusal_recovery import compose_refusal
from yoke_contracts.timestamps import utc_now

from yoke_core.domain import db_helpers
from yoke_core.domain.db_helpers import instant_parameter


class WatcherActivityRequest(BaseModel):
    pass


class WatcherActivityResponse(BaseModel):
    activity_at: datetime


def _connect_rw():
    return db_helpers.connect()


def handle_watcher_activity(request: FunctionCallRequest) -> HandlerOutcome:
    """Refresh session and claim liveness without changing the tool clock.

    Only real hook tool calls advance last_tool_call_at. The server supplies
    the heartbeat instant, so a caller cannot pin liveness in the future.
    """
    session_id = request.actor.session_id
    with _connect_rw() as conn:
        now = instant_parameter(conn, utc_now())
        row = conn.execute(
            "UPDATE harness_sessions SET last_heartbeat=%s "
            "WHERE session_id=%s AND ended_at IS NULL AND terminated_at IS NULL "
            "RETURNING last_heartbeat",
            (now, session_id),
        ).fetchone()
        if row is None:
            return HandlerOutcome(primary_success=False, error=FunctionError(
                code="watcher_owner_inactive",
                message=compose_refusal(
                    "watcher_owner_inactive: the wrapper has no active owning session",
                    recovery="Inspect the watcher capture, then restart from an active session",
                ),
            ))
        conn.execute(
            "UPDATE work_claims SET last_heartbeat=%s "
            "WHERE session_id=%s AND released_at IS NULL", (now, session_id),
        )
        conn.commit()
        return HandlerOutcome(result_payload={"activity_at": row["last_heartbeat"]})
