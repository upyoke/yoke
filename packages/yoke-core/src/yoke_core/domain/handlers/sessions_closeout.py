"""Registered non-destructive session closeout surface."""

from __future__ import annotations

from typing import Any, Dict

from pydantic import BaseModel

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)


class SessionsEndIfEmptyRequest(BaseModel):
    triggered_by: str = "cli"


class SessionsEndIfEmptyResponse(BaseModel):
    session_id: str
    status: str
    ended: bool
    active_claim_count: int
    session: Dict[str, Any] | None = None
    checkpoint_step: int | None = None
    max_chain_steps: int | None = None
    next_action: str | None = None


def handle_sessions_end_if_empty(
    request: FunctionCallRequest,
) -> HandlerOutcome:
    if request.target.kind != "global":
        return HandlerOutcome(
            primary_success=False,
            error=FunctionError(
                code="target_invalid",
                message="sessions.end_if_empty requires target.kind='global'",
                jsonpath="$.target.kind",
            ),
        )
    session_id = str(request.actor.session_id or "").strip()
    if not session_id:
        return HandlerOutcome(
            primary_success=False,
            error=FunctionError(
                code="session_required",
                message="sessions.end_if_empty requires actor.session_id",
                jsonpath="$.actor.session_id",
            ),
        )
    payload = SessionsEndIfEmptyRequest.model_validate(request.payload or {})

    from yoke_core.domain.db_helpers import connect
    from yoke_core.domain.sessions_render_end_if_empty import end_session_if_empty

    with connect() as conn:
        result = end_session_if_empty(
            conn,
            session_id,
            triggered_by=payload.triggered_by,
        )
    return HandlerOutcome(result_payload=result, primary_success=True)


__all__ = [
    "SessionsEndIfEmptyRequest",
    "SessionsEndIfEmptyResponse",
    "handle_sessions_end_if_empty",
]
