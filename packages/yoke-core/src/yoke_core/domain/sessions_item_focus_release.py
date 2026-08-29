"""Post-commit focus release for sessions that were working one item.

The companion to every item-scoped claim cleanup that releases other
sessions' claims in bulk — an item reaching a terminal status, a done
item's foreign claims, a stale item claim reclaimed for a new holder.
Those transactions run in item -> claim lock order, so the holder's
session row is written here, after the commit, under sorted session
locks alone.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from .sessions_claim_lifecycle_lock import lock_session_rows_for_claim_lifecycle
from .sessions_render_attribution import release_item_focus_if_current


def release_item_focus_for_sessions(
    conn: Any,
    item_id: int | str,
    released_holder_session_ids: Iterable[str],
    *,
    commit: bool = True,
) -> tuple[str, ...]:
    """Re-focus sessions whose focus still names this released item.

    A session that moved to different work after the item transaction
    committed retains that newer focus; a session still naming the item
    archives that focus and falls back to any remaining active claim
    through :func:`release_item_focus_if_current` (a plain clear when
    none). Returns the sessions whose focus was released.
    """
    session_ids = tuple(
        sorted(
            {
                str(session_id)
                for session_id in released_holder_session_ids
                if str(session_id)
            }
        )
    )
    if not session_ids:
        if commit:
            conn.commit()
        return ()

    lock_session_rows_for_claim_lifecycle(conn, session_ids)
    released = tuple(
        session_id
        for session_id in session_ids
        if release_item_focus_if_current(conn, session_id, item_id)
    )
    if commit:
        conn.commit()
    return released


__all__ = ["release_item_focus_for_sessions"]
