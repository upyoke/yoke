"""Registered-function handlers for message receipt mutations and leases."""

from __future__ import annotations

from yoke_contracts.api.function_call import FunctionCallRequest, HandlerOutcome
from yoke_contracts.session_control.models import (
    MessageAcknowledgeRequest,
    MessageCancelRequest,
    MessageLeaseRequest,
)
from yoke_core.domain.handlers.session_messages_common import (
    domain_error,
    failure,
    numeric_actor_id,
    open_connection,
    parse,
    require_global,
    require_top_level_message_actor,
)


def _parsed(request: FunctionCallRequest, model: type) -> object | HandlerOutcome:
    invalid = require_global(request)
    return invalid or parse(model, request)


def handle_message_acknowledge(request: FunctionCallRequest) -> HandlerOutcome:
    parsed = _parsed(request, MessageAcknowledgeRequest)
    if isinstance(parsed, HandlerOutcome):
        return parsed
    invalid = require_top_level_message_actor(request)
    if invalid:
        return invalid
    from yoke_core.domain.session_message_service import acknowledge_message

    session_id = str(request.actor.session_id or "").strip()
    if not session_id:
        return failure(
            "session_required", "recipient session is required", "$.actor.session_id"
        )
    conn = open_connection()
    try:
        from yoke_core.domain.session_control_request_identity import (
            registered_request_session_id,
        )

        if registered_request_session_id(conn, session_id) is None:
            return failure(
                "recipient_session_unregistered",
                "Fleet acknowledgments require a registered top-level session",
                "$.actor.session_id",
            )
        message = acknowledge_message(
            conn, message_id=parsed.message_id, session_id=session_id
        )
        return HandlerOutcome(result_payload={"message": message})
    except Exception as exc:
        conn.rollback()
        return domain_error(exc)
    finally:
        conn.close()


def handle_message_cancel(request: FunctionCallRequest) -> HandlerOutcome:
    parsed = _parsed(request, MessageCancelRequest)
    if isinstance(parsed, HandlerOutcome):
        return parsed
    from yoke_core.domain.session_message_service import cancel_message

    conn = open_connection()
    try:
        message = cancel_message(
            conn,
            message_id=parsed.message_id,
            actor_id=numeric_actor_id(request),
        )
        return HandlerOutcome(result_payload={"message": message})
    except Exception as exc:
        conn.rollback()
        return domain_error(exc)
    finally:
        conn.close()


def handle_message_lease(request: FunctionCallRequest) -> HandlerOutcome:
    parsed = _parsed(request, MessageLeaseRequest)
    if isinstance(parsed, HandlerOutcome):
        return parsed
    invalid = require_top_level_message_actor(request)
    if invalid:
        return invalid
    from yoke_core.domain.session_message_delivery import lease_for_hook

    session_id = str(request.actor.session_id or "").strip()
    if not session_id or parsed.session_id != session_id:
        return failure(
            "lease_self_only",
            "a hook may lease messages only for its own bound session",
            "$.payload.session_id",
        )
    conn = open_connection()
    try:
        from yoke_core.domain.session_control_request_identity import (
            registered_request_session_id,
        )

        if registered_request_session_id(conn, session_id) is None:
            return failure(
                "recipient_session_unregistered",
                "Fleet hook leases require a registered top-level session",
                "$.actor.session_id",
            )
        lease = lease_for_hook(
            conn,
            session_id=session_id,
            hook_event=parsed.hook_event,
            limit=parsed.limit,
        )
        return HandlerOutcome(result_payload=lease or {"lease_id": "", "messages": []})
    except Exception as exc:
        conn.rollback()
        return domain_error(exc)
    finally:
        conn.close()


__all__ = [
    "handle_message_acknowledge",
    "handle_message_cancel",
    "handle_message_lease",
]
