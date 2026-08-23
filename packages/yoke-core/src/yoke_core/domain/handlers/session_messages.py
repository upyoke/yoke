"""Registered-function handlers for session-message reads and sending."""

from __future__ import annotations

from typing import Any, Callable

from yoke_contracts.api.function_call import FunctionCallRequest, HandlerOutcome
from yoke_contracts.session_control.models import (
    MessageGetRequest,
    MessageListRequest,
    MessagePreviewRequest,
    MessageSendRequest,
)
from yoke_core.domain.handlers.session_messages_common import (
    domain_error,
    numeric_actor_id,
    open_connection,
    parse,
    require_global,
)


def _handle(
    request: FunctionCallRequest,
    model: Any,
    operation: Callable[[Any, Any, int], dict[str, Any]],
) -> HandlerOutcome:
    invalid = require_global(request)
    if invalid:
        return invalid
    parsed = parse(model, request)
    if isinstance(parsed, HandlerOutcome):
        return parsed
    conn = open_connection()
    try:
        return HandlerOutcome(
            result_payload=operation(conn, parsed, numeric_actor_id(request))
        )
    except Exception as exc:
        conn.rollback()
        return domain_error(exc)
    finally:
        conn.close()


def handle_message_preview(request: FunctionCallRequest) -> HandlerOutcome:
    from yoke_core.domain.session_message_service import preview_message

    return _handle(
        request,
        MessagePreviewRequest,
        lambda conn, body, actor_id: preview_message(
            conn, actor_id=actor_id, selector=body.selector
        ),
    )


def handle_message_send(request: FunctionCallRequest) -> HandlerOutcome:
    from yoke_core.domain.session_message_service import send_message
    from yoke_core.domain.session_control_request_identity import (
        registered_request_session_id,
    )

    return _handle(
        request,
        MessageSendRequest,
        lambda conn, body, actor_id: send_message(
            conn,
            actor_id=actor_id,
            sender_session_id=registered_request_session_id(
                conn,
                request.actor.session_id,
            ),
            selector=body.selector,
            body=body.body,
            idempotency_key=body.idempotency_key,
            supplied_confirmation_token=body.confirmation_token,
        ),
    )


def handle_message_list(request: FunctionCallRequest) -> HandlerOutcome:
    from yoke_core.domain.session_message_service import list_messages

    return _handle(
        request,
        MessageListRequest,
        lambda conn, body, actor_id: {
            "messages": (
                messages := list_messages(
                    conn,
                    actor_id=actor_id,
                    caller_session_id=request.actor.session_id or None,
                    state=body.state,
                    session_id=body.session_id,
                    limit=body.limit,
                )
            ),
            "count": len(messages),
        },
    )


def handle_message_get(request: FunctionCallRequest) -> HandlerOutcome:
    from yoke_core.domain.session_message_service import get_message

    return _handle(
        request,
        MessageGetRequest,
        lambda conn, body, actor_id: {
            "message": get_message(
                conn,
                message_id=body.message_id,
                actor_id=actor_id,
                session_id=request.actor.session_id or None,
            )
        },
    )


__all__ = [
    "handle_message_get",
    "handle_message_list",
    "handle_message_preview",
    "handle_message_send",
]
