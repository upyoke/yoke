"""Durable relay-launch context for registered harness sessions."""

from typing import Any

from yoke_core.domain.session_launch_origin import session_launch_origin


def session_was_relay_launched(conn: Any, session_id: str) -> bool:
    """Read the immutable session origin used by continuation and Stop rules."""
    return bool(session_id) and session_launch_origin(conn, session_id) == "yoke"


__all__ = ["session_was_relay_launched"]
