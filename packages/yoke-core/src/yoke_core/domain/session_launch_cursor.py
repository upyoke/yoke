"""Canonical cursor keys for descending session launch history."""

import base64
from datetime import datetime

from yoke_contracts.timestamps import format_instant, parse_instant
from yoke_core.domain.json_helper import dumps_compact, loads_text
from yoke_core.domain.session_launch_types import SessionLaunchError


_CURSOR_VERSION = 1


def encode_launch_cursor(created_at: datetime | str, launch_id: str) -> str:
    raw = dumps_compact(
        {
            "v": _CURSOR_VERSION,
            "created_at": format_instant(parse_instant(created_at)),
            "launch_id": launch_id,
        }
    )
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def decode_launch_cursor(cursor: str | None) -> tuple[datetime, str] | None:
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
            "launch_id",
        }:
            raise ValueError
        if type(payload["v"]) is not int or payload["v"] != _CURSOR_VERSION:
            raise ValueError
        created_at = payload["created_at"]
        launch_id = payload["launch_id"]
        instant = parse_instant(created_at)
        if created_at != format_instant(instant):
            raise ValueError
        if not isinstance(launch_id, str) or not launch_id:
            raise ValueError
        return instant, launch_id
    except (TypeError, UnicodeError, ValueError):
        raise SessionLaunchError(
            "cursor_invalid",
            "the launch history cursor is unreadable or predates the instant contract; "
            "clear it and load the first history page again",
        ) from None
