"""Backlog session attribution — best-effort current-item bookkeeping
on the harness session row, plus the backlog-write-path alias of the
canonical ambient session resolver.
"""

from __future__ import annotations

from typing import Any, Optional

from yoke_core.domain.session_ambient_identity import (
    resolve_ambient_session_id,
)


def _maybe_set_session_current_item(
    conn: Any,
    item_id: int,
    session_id: Optional[str],
) -> None:
    """Best-effort session attribution update for create/status mutation paths.

    Filing or updating an item attributes it to the session; it does not
    claim it. When an active work claim already holds this session on
    other work, the touched item is recorded as the recent item so the
    focus slot keeps naming the claimed work.
    """
    if not session_id:
        return
    try:
        from yoke_core.domain.sessions import (
            attribution_takes_focus,
            record_recent_item,
            set_current_item,
        )

        if attribution_takes_focus(conn, session_id, str(item_id)):
            set_current_item(conn, session_id, str(item_id))
        else:
            record_recent_item(conn, session_id, str(item_id))
    except Exception:
        # Attribution should never block the write path.
        return


def _current_session_id() -> str:
    return resolve_ambient_session_id() or ""


__all__ = ["_maybe_set_session_current_item", "_current_session_id"]
