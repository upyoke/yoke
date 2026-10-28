"""Tell senders when session cleanup cancels undelivered mail."""

from __future__ import annotations

import logging
from typing import Any

from yoke_contracts.session_control.models import RecipientSelector

_LOGGER = logging.getLogger(__name__)


def notify_cancelled_message_senders(
    conn: Any, messages: list[dict], *, session_id: str, reason: str
) -> None:
    """Send once per cancelled envelope after commit; never fail cleanup."""
    from .session_message_service import send_message

    for message in messages:
        sender = str(message.get("sender_session_id") or "").strip()
        if not sender:
            continue
        message_id = message["message_id"]
        try:
            send_message(
                conn,
                actor_id=message["sender_actor_id"],
                sender_session_id=None,
                selector=RecipientSelector(session_ids=[sender]),
                body=(
                    f"Message {message_id} was not delivered to session {session_id}: "
                    f"{reason}. Its pending recipient was cancelled. "
                    "Address the person separately if the request is still needed."
                ),
                idempotency_key=f"message-undelivered:{message_id}:{session_id}",
                idempotency_intent_only=True,
            )
        except Exception:
            _LOGGER.warning(
                "message_cancellation_notice_failed: message %s, recipient %s, "
                "reason %s; inspect the original message and address the person "
                "separately if needed",
                message_id,
                session_id,
                reason,
                exc_info=True,
            )
