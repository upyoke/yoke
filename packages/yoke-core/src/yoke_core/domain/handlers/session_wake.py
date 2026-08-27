"""Registered handler for an explicit native session wake."""

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

    from yoke_core.domain.session_manual_wake import (
        request_session_wake,
        wait_for_session_wake_result,
    )
    from yoke_core.domain.session_control_request_identity import (
        registered_request_session_id,
    )

    conn = open_connection()
    try:
        raw_session_id = str(request.actor.session_id or "").strip()
        caller_session_id = registered_request_session_id(conn, raw_session_id)
        if raw_session_id and caller_session_id is None:
            from yoke_core.domain.session_message_types import SessionMessageError

            raise SessionMessageError(
                "sender_session_unregistered",
                "Session wake callers must name a registered top-level session",
                jsonpath="$.actor.session_id",
            )
        result = request_session_wake(
            conn,
            actor_id=numeric_actor_id(request),
            caller_session_id=caller_session_id,
            session_id=body.session_id,
            item_ref=body.item_ref,
            prompt=body.prompt,
            idempotency_key=body.idempotency_key,
        )
        return HandlerOutcome(result_payload=wait_for_session_wake_result(conn, result))
    except SessionError as exc:
        conn.rollback()
        return failure(exc.code, str(exc))
    except Exception as exc:
        conn.rollback()
        return domain_error(exc)
    finally:
        conn.close()


__all__ = ["handle_session_wake"]
