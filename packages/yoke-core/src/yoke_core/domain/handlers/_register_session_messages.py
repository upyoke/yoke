"""Registered Fleet message operations kept separate from relay wiring."""

from __future__ import annotations

from typing import Any, Callable

from yoke_contracts.session_control import models as _models
from yoke_core.domain.handlers import session_messages as _messages
from yoke_core.domain.handlers import session_messages_receipts as _receipts


def register_message_functions(
    registry: Any, register_one: Callable[..., None]
) -> None:
    specs = (
        (
            "preview",
            _messages.handle_message_preview,
            _models.MessagePreviewRequest,
            _models.MessagePreviewResponse,
            [],
        ),
        (
            "send",
            _messages.handle_message_send,
            _models.MessageSendRequest,
            _models.MessageSendResponse,
            [
                "session_messages_insert",
                "session_message_recipients_insert",
                "actor_message_recipients_insert",
            ],
        ),
        (
            "list",
            _messages.handle_message_list,
            _models.MessageListRequest,
            _models.MessageListResponse,
            [],
        ),
        (
            "get",
            _messages.handle_message_get,
            _models.MessageGetRequest,
            _models.MessageGetResponse,
            [],
        ),
        (
            "acknowledge",
            _receipts.handle_message_acknowledge,
            _models.MessageAcknowledgeRequest,
            _models.MessageMutationResponse,
            [
                "session_message_recipients_update",
                "actor_message_recipients_update",
                "work_claims_update_released_at",
            ],
        ),
        (
            "cancel",
            _receipts.handle_message_cancel,
            _models.MessageCancelRequest,
            _models.MessageMutationResponse,
            [
                "session_messages_update",
                "session_message_recipients_update",
                "actor_message_recipients_update",
            ],
        ),
        (
            "lease",
            _receipts.handle_message_lease,
            _models.MessageLeaseRequest,
            _models.MessageLeaseResponse,
            ["session_message_recipients_update", "session_message_attempts_insert"],
        ),
    )
    for operation, handler, request_model, response_model, effects in specs:
        register_one(
            registry,
            f"session_control.message.{operation}",
            handler,
            request_model,
            response_model,
            side_effects=effects,
            owner_module=handler.__module__,
            adapter_status="internal" if operation == "lease" else "live",
        )


__all__ = ["register_message_functions"]
