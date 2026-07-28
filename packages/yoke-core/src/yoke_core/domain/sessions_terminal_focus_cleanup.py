"""Post-commit session-focus cleanup for a terminal item."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from . import db_backend
from .sessions_claim_lifecycle_lock import lock_session_rows_for_claim_lifecycle
from .sessions_queries import normalize_claim_item_id


def clear_terminal_item_focuses(
    conn: Any,
    item_id: int | str,
    released_holder_session_ids: Iterable[str],
    *,
    commit: bool = True,
) -> tuple[str, ...]:
    """Clear only session focuses that still name the terminal item.

    This is the post-commit companion to item-scoped terminal claim cleanup.
    It acquires only sorted session-row locks, so it never reverses the
    session -> item -> claim order used by claim lifecycle transactions.
    A session that moved to different work after the item transaction
    committed retains that newer focus.
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
    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    placeholders = ", ".join(marker for _ in session_ids)
    rows = conn.execute(
        "SELECT session_id, current_item_id, current_item_set_at "
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
        conn.execute(
            "UPDATE harness_sessions SET "
            f"recent_item_id = {marker}, recent_item_recorded_at = {marker}, "
            "current_item_id = NULL, current_item_set_at = NULL "
            f"WHERE session_id = {marker} AND current_item_id = {marker}",
            (
                current_item_id,
                row["current_item_set_at"],
                session_id,
                current_item_id,
            ),
        )
        cleared.append(session_id)

    if commit:
        conn.commit()
    return tuple(cleared)


__all__ = ["clear_terminal_item_focuses"]
