"""Normalize fleet message receipts for one polling snapshot."""

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping

from yoke_contracts.timestamps import parse_instant


@dataclass(frozen=True)
class EnvelopeRow:
    """One durable message receipt: a message plus one recipient."""

    message_id: str
    recipient_session_id: str
    sender_session_id: str
    state: str
    injection_count: int
    created_at: datetime | None

    @property
    def key(self) -> tuple[str, str]:
        return (self.message_id, self.recipient_session_id)


def envelope_rows(
    result: Mapping[str, Any],
) -> dict[tuple[str, str], EnvelopeRow]:
    """Normalize a message listing into per-recipient receipt rows."""
    rows: dict[tuple[str, str], EnvelopeRow] = {}
    for message in result.get("messages") or []:
        if not isinstance(message, Mapping):
            continue
        message_id = str(message.get("message_id") or "")
        sender = str(message.get("sender_session_id") or "")
        created = (
            parse_instant(message["created_at"])
            if message.get("created_at") is not None
            else None
        )
        for recipient in message.get("recipients") or []:
            if not isinstance(recipient, Mapping):
                continue
            session_id = str(recipient.get("session_id") or "")
            if not message_id or not session_id:
                continue
            row = EnvelopeRow(
                message_id=message_id,
                recipient_session_id=session_id,
                sender_session_id=sender,
                state=str(recipient.get("state") or "unknown"),
                injection_count=int(recipient.get("injection_count") or 0),
                created_at=(
                    parse_instant(recipient["created_at"])
                    if recipient.get("created_at") is not None
                    else created
                ),
            )
            rows[row.key] = row
    return rows
