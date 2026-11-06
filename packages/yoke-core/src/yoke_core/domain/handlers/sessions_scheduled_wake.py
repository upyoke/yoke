"""Registered timed self-wake operation."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)
from yoke_core.domain.db_helpers import connect
from yoke_core.domain.session_message_types import SessionMessageError
from yoke_core.domain.session_scheduled_wake import schedule_session_wake


class ScheduledWakeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    at: datetime
    reason: str


class ScheduledWakeResponse(BaseModel):
    model_config = ConfigDict(extra="allow")
    wake_id: str
    scheduled_at: str


def handle_schedule(request: FunctionCallRequest) -> HandlerOutcome:
    try:
        body = ScheduledWakeRequest.model_validate(request.payload or {})
        if body.at.tzinfo is None:
            raise ValueError("--at must include a UTC offset")
        session_id = request.actor.session_id
        if not session_id:
            raise ValueError("run this command in the session that needs the recheck")
        with connect() as conn:
            result = schedule_session_wake(
                conn,
                session_id=session_id,
                actor_id=request.actor.actor_id,
                at=body.at,
                reason=body.reason,
            )
            conn.commit()
        return HandlerOutcome(result_payload=result)
    except (ValueError, SessionMessageError) as exc:
        return HandlerOutcome(
            primary_success=False,
            error=FunctionError(
                code=getattr(exc, "code", "scheduled_wake_invalid"),
                message=f"{exc} Retry yoke sessions wake schedule with a future --at and --reason.",
            ),
        )
