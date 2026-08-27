"""Registered handler for an operator-forced native session wake."""

from __future__ import annotations

from yoke_contracts.api.function_call import FunctionCallRequest, HandlerOutcome
from yoke_contracts.session_control.wake import SessionWakeRequest
from yoke_core.domain.handlers.session_messages_common import (
    domain_error,
    failure,
    numeric_actor_id,
    open_connection,
    parse,
    require_global,
    require_top_level_message_actor,
)
from yoke_core.domain.sessions_analytics import SessionError


def handle_session_wake(request: FunctionCallRequest) -> HandlerOutcome:
    if invalid := require_global(request):
        return invalid
    if invalid := require_top_level_message_actor(request):
        return invalid
    body = parse(SessionWakeRequest, request)
    if isinstance(body, HandlerOutcome):
        return body
    caller_session_id = str(request.actor.session_id or "").strip()
    if not caller_session_id:
        return failure(
            "SESSION_CONTROL_AUTHORITY_REQUIRED",
            "Manual wake requires a registered operator or steering session.",
            "$.actor.session_id",
        )

    from yoke_core.domain.session_manual_wake import (
        request_manual_wake,
        wait_for_manual_wake_result,
    )

    conn = open_connection()
    try:
        result = request_manual_wake(
            conn,
            actor_id=numeric_actor_id(request),
            caller_session_id=caller_session_id,
            session_id=body.session_id,
            item_ref=body.item_ref,
            prompt=body.prompt,
        )
        return HandlerOutcome(result_payload=wait_for_manual_wake_result(conn, result))
    except SessionError as exc:
        conn.rollback()
        return failure(exc.code, str(exc))
    except Exception as exc:
        conn.rollback()
        return domain_error(exc)
    finally:
        conn.close()


__all__ = ["handle_session_wake"]
