"""Canonical cursor keys for descending Fleet message history."""

import base64
from datetime import datetime

from yoke_contracts.timestamps import format_instant, parse_instant
from yoke_core.domain.json_helper import dumps_compact, loads_text
from yoke_core.domain.session_message_types import SessionMessageError


_CURSOR_VERSION = 1


def encode_message_cursor(created_at: datetime | str, message_id: str) -> str:
    raw = dumps_compact(
        {
            "v": _CURSOR_VERSION,
            "created_at": format_instant(parse_instant(created_at)),
            "message_id": message_id,
        }
    )
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def decode_message_cursor(cursor: str | None) -> tuple[datetime, str] | None:
    if cursor is None:
        return None
    try:
        padding = "=" * (-len(cursor) % 4)
        payload = loads_text(
            base64.urlsafe_b64decode((cursor + padding).encode()).decode()
        )
        if not isinstance(payload, dict) or set(payload) != {
            "v",
            "created_at",
            "message_id",
        }:
            raise ValueError
        if type(payload["v"]) is not int or payload["v"] != _CURSOR_VERSION:
            raise ValueError
        created_at = payload["created_at"]
        message_id = payload["message_id"]
        instant = parse_instant(created_at)
        if created_at != format_instant(instant):
            raise ValueError
        if not isinstance(message_id, str) or not message_id:
            raise ValueError
        return instant, message_id
    except (TypeError, UnicodeError, ValueError):
        raise SessionMessageError(
            "cursor_invalid",
            "the settled-message cursor is unreadable or predates the instant contract; "
            "clear it and load the first Messages page again",
        ) from None
