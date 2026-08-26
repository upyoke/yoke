"""Event vocabulary and emitter for permanent session termination."""

from __future__ import annotations

from typing import Any


EVENT_SESSION_TERMINATED = "SessionTerminated"


def emit_session_terminated(
    session_id: str,
    *,
    context: dict[str, Any],
) -> None:
    from yoke_core.domain.sessions_analytics import _emit_session_event

    _emit_session_event(
        EVENT_SESSION_TERMINATED,
        session_id=session_id,
        context=context,
    )


__all__ = ["EVENT_SESSION_TERMINATED", "emit_session_terminated"]
