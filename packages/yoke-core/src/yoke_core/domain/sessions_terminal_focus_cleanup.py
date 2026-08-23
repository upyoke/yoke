"""Post-commit session-focus cleanup for a terminal item."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from .sessions_claim_lifecycle_lock import lock_session_rows_for_claim_lifecycle
from .sessions_queries import normalize_claim_item_id
from .sessions_render_attribution import release_current_item_focus


def clear_terminal_item_focuses(
    conn: Any,
    item_id: int | str,
    released_holder_session_ids: Iterable[str],
    *,
    commit: bool = True,
) -> tuple[str, ...]:
    """Re-focus sessions whose focus named this now-terminal item.

    This is the post-commit companion to item-scoped terminal claim cleanup.
    It acquires only sorted session-row locks, so it never reverses the
    session -> item -> claim order used by claim lifecycle transactions.
    A session that moved to different work after the item transaction
    committed retains that newer focus; a session still naming the terminal
    item archives that focus and falls back to any remaining active claim
    through :func:`release_current_item_focus` (a plain clear when none).
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
    placeholders = ", ".join("%s" for _ in session_ids)
    rows = conn.execute(
        "SELECT session_id, current_item_id "
        f"FROM harness_sessions WHERE session_id IN ({placeholders}) "
        "ORDER BY session_id",
        session_ids,
    ).fetchall()
    terminal_item_id = normalize_claim_item_id(str(item_id))
    cleared: list[str] = []
    for row in rows:
        current_item_id = row["current_item_id"]
        if (
            current_item_id is None
            or normalize_claim_item_id(str(current_item_id)) != terminal_item_id
        ):
            continue
        session_id = str(row["session_id"])
        release_current_item_focus(conn, session_id, commit=False)
        cleared.append(session_id)

    if commit:
        conn.commit()
    return tuple(cleared)


__all__ = ["clear_terminal_item_focuses"]
