"""Durable relay-launch context for registered harness sessions."""

from typing import Any

from yoke_core.domain.session_launch_origin import session_launch_origin


def session_was_relay_launched(conn: Any, session_id: str) -> bool:
    """Read the immutable session origin used by continuation and Stop rules."""
    if not session_id:
        return False
    try:
        return session_launch_origin(conn, session_id) == "yoke"
    except Exception:  # noqa: BLE001 - never impose an unenforceable Stop denial
        return True


__all__ = ["session_was_relay_launched"]
