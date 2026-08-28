"""Keep a newly bound launch session alive while it enters its mandate."""

from __future__ import annotations

from typing import Any

from .session_keepalive import hold_session_keepalive
from .session_launch_store import parse_time


LAUNCH_REGISTRATION_GRACE_REASON = "launch registration grace"


def hold_launch_registration_grace(conn: Any, session_id: str, *, now: str) -> None:
    """Take the existing bounded lease inside the launch-binding transaction."""
    hold_session_keepalive(
        conn,
        session_id,
        reason=LAUNCH_REGISTRATION_GRACE_REASON,
        now=parse_time(now),
        commit=False,
    )


__all__ = ["LAUNCH_REGISTRATION_GRACE_REASON", "hold_launch_registration_grace"]
