"""Backlog session attribution — recording the item a session touched,
plus the backlog-write-path alias of the canonical ambient session
resolver.
"""

from __future__ import annotations

from typing import Any, Optional

from yoke_core.domain.session_ambient_identity import (
    resolve_ambient_session_id,
)


def record_touched_item(
    conn: Any,
    item_id: int,
    session_id: Optional[str],
) -> None:
    """Record a touched item as this session's recent item.

    Filing or updating an item attributes it to the session; it does not
    claim it. The focus slot (``current_item_id``) names the item a
    session is *working*, and only the work-claim lifecycle writes it —
    so a session that files an item it never claims, or a steering seat
    that files on someone else's behalf, keeps the focus it had.
    """
    if not session_id:
        return
    try:
        from yoke_core.domain.sessions import record_recent_item

        record_recent_item(conn, session_id, str(item_id))
    except Exception:
        # Attribution should never block the write path.
        return


def _current_session_id() -> str:
    return resolve_ambient_session_id() or ""


__all__ = ["record_touched_item", "_current_session_id"]
