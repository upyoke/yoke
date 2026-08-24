"""Session current-item attribution helpers."""

from __future__ import annotations

from typing import Any, Dict, Optional

from . import db_backend
from .sessions_analytics import SessionError
from .sessions_queries import _now_iso, normalize_claim_item_id, normalize_session_item_id


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def focus_fallback_item_id(
    conn: Any,
    session_id: str,
    *,
    excluding_item_id: Optional[str] = None,
) -> Optional[str]:
    """Return the newest still-active item claim's id for a session.

    The fallback candidate is the most recently claimed item whose claim
    has not been released, optionally skipping one item (the claim being
    released right now). Epic-task and process claims never feed the
    item-focus fallback. Returns ``None`` when nothing remains.
    """
    params: list[Any] = [session_id]
    sql = (
        "SELECT item_id FROM work_claims "
        f"WHERE session_id = {_p(conn)} AND target_kind = 'item' "
        "AND released_at IS NULL AND item_id IS NOT NULL"
    )
    if excluding_item_id is not None:
        excluded = normalize_claim_item_id(str(excluding_item_id))
        sql += f" AND item_id <> {_p(conn)}"
        params.append(int(excluded) if excluded.isdigit() else excluded)
    sql += " ORDER BY claimed_at DESC, id DESC LIMIT 1"
    row = conn.execute(sql, tuple(params)).fetchone()
    if row is None or row["item_id"] is None:
        return None
    return normalize_claim_item_id(str(row["item_id"]))


def attribution_takes_focus(
    conn: Any,
    session_id: str,
    item_id: str,
) -> bool:
    """Whether touching ``item_id`` may become this session's focus.

    Filing or updating an item is attribution, not a claim on it. It may
    take the focus slot only when nothing better holds it: the session
    already claims this item, or it holds no active item claim at all.
    A session working claimed work keeps pointing at that work, so the
    roster never renders a filed item as the item this session is on.
    """
    claimed = {
        normalize_claim_item_id(str(row["item_id"]))
        for row in conn.execute(
            "SELECT item_id FROM work_claims "
            f"WHERE session_id = {_p(conn)} AND target_kind = 'item' "
            "AND released_at IS NULL AND item_id IS NOT NULL",
            (session_id,),
        ).fetchall()
    }
    return not claimed or normalize_claim_item_id(str(item_id)) in claimed


def record_recent_item(
    conn: Any,
    session_id: str,
    item_id: str,
    *,
    commit: bool = True,
) -> None:
    """Record an item this session touched without taking its focus.

    The attribution counterpart to :func:`set_current_item` for a
    session whose focus belongs to claimed work. Silently no-ops if the
    session is ended.
    """
    item_id = normalize_session_item_id(item_id)
    row = conn.execute(
        "SELECT ended_at FROM harness_sessions WHERE session_id = %s",
        (session_id,),
    ).fetchone()
    if row is None:
        raise SessionError("NOT_FOUND", f"Session '{session_id}' not found.")
    if row[0] is not None:
        return
    conn.execute(
        "UPDATE harness_sessions SET "
        "recent_item_id = %s, recent_item_status = NULL, "
        "recent_item_recorded_at = %s "
        "WHERE session_id = %s",
        (item_id, _now_iso(), session_id),
    )
    if commit:
        conn.commit()


def set_current_item(
    conn: Any,
    session_id: str,
    item_id: str,
    item_status: Optional[str] = None,
    *,
    commit: bool = True,
) -> None:
    """Set the current item focus for a session.

    Before setting the new item, copies current values to recent_item_*
    fields if ``current_item_id`` was non-NULL.  Silently no-ops if the
    session is ended.

    Args:
        conn: DB connection.
        session_id: Session to update.
        item_id: Item identifier (stored bare numeric when possible).
        item_status: Optional status to record in ``recent_item_status``
            when the current item becomes the recent item.
    """
    now = _now_iso()
    item_id = normalize_session_item_id(item_id)
    row = conn.execute(
        "SELECT ended_at, current_item_id, current_item_set_at "
        "FROM harness_sessions WHERE session_id = %s",
        (session_id,),
    ).fetchone()
    if row is None:
        raise SessionError("NOT_FOUND", f"Session '{session_id}' not found.")
    if row[0] is not None:
        # Session ended — silently no-op
        return

    # Move current to recent if non-NULL
    if row[1] is not None:
        conn.execute(
            "UPDATE harness_sessions SET "
            "recent_item_id = %s, recent_item_status = %s, recent_item_recorded_at = %s "
            "WHERE session_id = %s",
            (row[1], item_status, row[2], session_id),
        )

    conn.execute(
        "UPDATE harness_sessions SET "
        "current_item_id = %s, current_item_set_at = %s "
        "WHERE session_id = %s",
        (item_id, now, session_id),
    )
    if commit:
        conn.commit()


def get_session_attribution(
    conn: Any,
    session_id: str,
) -> Dict[str, Any]:
    """Return attribution fields for a session as a dict.

    Returns an empty dict if the session is not found.
    """
    row = conn.execute(
        "SELECT current_item_id, current_item_set_at, "
        "recent_item_id, recent_item_status, recent_item_recorded_at "
        "FROM harness_sessions WHERE session_id = %s",
        (session_id,),
    ).fetchone()
    if row is None:
        return {}
    return {
        "current_item_id": row[0],
        "current_item_set_at": row[1],
        "recent_item_id": row[2],
        "recent_item_status": row[3],
        "recent_item_recorded_at": row[4],
    }


def clear_current_item(
    conn: Any,
    session_id: str,
    *,
    commit: bool = True,
) -> None:
    """Clear the current item focus, moving current to recent first.

    Args:
        conn: DB connection.
        session_id: Session to update.
    """
    row = conn.execute(
        "SELECT current_item_id, current_item_set_at "
        "FROM harness_sessions WHERE session_id = %s",
        (session_id,),
    ).fetchone()
    if row is None:
        raise SessionError("NOT_FOUND", f"Session '{session_id}' not found.")

    # Move current to recent if non-NULL
    if row[0] is not None:
        conn.execute(
            "UPDATE harness_sessions SET "
            "recent_item_id = %s, recent_item_recorded_at = %s "
            "WHERE session_id = %s",
            (row[0], row[1], session_id),
        )

    conn.execute(
        "UPDATE harness_sessions SET "
        "current_item_id = NULL, current_item_set_at = NULL "
        "WHERE session_id = %s",
        (session_id,),
    )
    if commit:
        conn.commit()


def release_current_item_focus(
    conn: Any,
    session_id: str,
    *,
    commit: bool = True,
) -> None:
    """Archive current focus to recent, then fall back to another claim.

    The claim-release counterpart of :func:`clear_current_item`: instead
    of leaving the session with no focus, it re-focuses the newest
    still-active item claim (if any), so a session holding several item
    claims keeps pointing at real work when the focused claim is
    released. No-op when the session has no focus; a missing fallback
    clears focus the same way :func:`clear_current_item` does.
    """
    row = conn.execute(
        "SELECT current_item_id, current_item_set_at "
        "FROM harness_sessions WHERE session_id = %s",
        (session_id,),
    ).fetchone()
    if row is None:
        raise SessionError("NOT_FOUND", f"Session '{session_id}' not found.")
    current = row[0]
    if current is None:
        return
    conn.execute(
        "UPDATE harness_sessions SET "
        "recent_item_id = %s, recent_item_recorded_at = %s "
        "WHERE session_id = %s",
        (current, row[1], session_id),
    )
    fallback = focus_fallback_item_id(
        conn,
        session_id,
        excluding_item_id=str(current),
    )
    conn.execute(
        "UPDATE harness_sessions SET "
        "current_item_id = %s, current_item_set_at = %s "
        "WHERE session_id = %s",
        (fallback, _now_iso() if fallback is not None else None, session_id),
    )
    if commit:
        conn.commit()


__all__ = [
    "attribution_takes_focus",
    "clear_current_item",
    "focus_fallback_item_id",
    "get_session_attribution",
    "record_recent_item",
    "release_current_item_focus",
    "set_current_item",
]
