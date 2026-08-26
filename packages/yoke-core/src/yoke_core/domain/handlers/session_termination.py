"""Registered handler for permanent session termination."""

from __future__ import annotations

from yoke_contracts.api.function_call import FunctionCallRequest, HandlerOutcome
from yoke_contracts.session_control.termination import SessionTerminateRequest
from yoke_core.domain.handlers.session_messages_common import (
    failure,
    numeric_actor_id,
    open_connection,
    parse,
    require_global,
    require_top_level_message_actor,
)
from yoke_core.domain.sessions_analytics import SessionError


def handle_session_terminate(request: FunctionCallRequest) -> HandlerOutcome:
    if invalid := require_global(request):
        return invalid
    if invalid := require_top_level_message_actor(request):
        return invalid
    body = parse(SessionTerminateRequest, request)
    if isinstance(body, HandlerOutcome):
        return body
    caller_session_id = str(request.actor.session_id or "").strip()
    if not caller_session_id:
        return failure(
            "TERMINATION_AUTHORITY_REQUIRED",
            "Session termination requires a registered calling session.",
            "$.actor.session_id",
        )

    from yoke_core.domain.session_termination import terminate_session

    conn = open_connection()
    try:
        result = terminate_session(
            conn,
            target_session_id=body.session_id,
            actor_id=numeric_actor_id(request),
            caller_session_id=caller_session_id,
            reason=body.reason,
            override_chain_end=body.override_chain_end,
            chain_end_rationale=body.chain_end_rationale,
        )
        return HandlerOutcome(result_payload=result)
    except SessionError as exc:
        conn.rollback()
        return failure(exc.code, str(exc))
    except Exception as exc:
        conn.rollback()
        return failure("session_termination_rejected", str(exc))
    finally:
        conn.close()


__all__ = ["handle_session_terminate"]
