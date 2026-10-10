"""Versioned exact-instant cursor for ended session history."""

from __future__ import annotations

import base64
from datetime import datetime

from yoke_contracts.timestamps import format_instant, parse_instant
from yoke_core.domain.json_helper import dumps_compact, loads_text


def encode(activity_at: datetime | str, session_id: str) -> str:
    raw = dumps_compact(
        {"v": 1, "activity_at": format_instant(activity_at), "session_id": session_id}
    )
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def decode(value: str | None) -> tuple[datetime, str] | None:
    if value is None:
        return None
    try:
        padding = "=" * (-len(value) % 4)
        payload = loads_text(
            base64.urlsafe_b64decode((value + padding).encode()).decode()
        )
        if not isinstance(payload, dict) or set(payload) != {
            "v",
            "activity_at",
            "session_id",
        }:
            raise ValueError
        if type(payload["v"]) is not int or payload["v"] != 1:
            raise ValueError
        activity, session_id = payload["activity_at"], payload["session_id"]
        if (
            not isinstance(activity, str)
            or not isinstance(session_id, str)
            or not session_id
        ):
            raise ValueError
        parsed = parse_instant(activity)
        if format_instant(parsed) != activity:
            raise ValueError
        return parsed, session_id
    except (KeyError, TypeError, UnicodeError, ValueError):
        raise ValueError(
            "history.cursor is invalid; clear it and reload the first history page"
        ) from None
