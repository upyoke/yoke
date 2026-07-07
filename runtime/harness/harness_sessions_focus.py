"""Focus-tracking primitives + identity / formatting helpers for the harness_sessions
write paths.

Owns the small private surface every harness_sessions writer reaches
for: current/recent item rotation, active-session preconditions,
``YOK-N``/integer item-id normalization, and the timestamp/format
formatters used across the cmd functions.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

from yoke_core.domain.db_helpers import query_one


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _format_row(row) -> str:
    return "|".join("" if v is None else str(v) for v in tuple(row))


def _normalize_item_id(raw: str) -> str:
    """Normalize numeric item IDs to bare numeric, preserve sentinels."""
    bare = re.sub(r"^[Yy][Oo][Kk]-", "", raw)
    if bare.isdigit():
        bare = bare.lstrip("0") or "0"
        return bare
    return raw


def _legacy_item_id(raw: str) -> str:
    bare = re.sub(r"^[Yy][Oo][Kk]-", "", raw)
    if bare.isdigit():
        bare = bare.lstrip("0") or "0"
        return f"YOK-{bare}"
    return raw


def _set_current_item(conn, session_id: str, item_id: str) -> None:
    """Mirror the harness session's current focus into harness_sessions."""
    item_id = _normalize_item_id(item_id)
    row = query_one(
        conn,
        "SELECT current_item_id, current_item_set_at FROM harness_sessions WHERE session_id=%s",
        (session_id,),
    )
    if row is None:
        return
    if row["current_item_id"]:
        conn.execute(
            "UPDATE harness_sessions SET recent_item_id=%s, recent_item_recorded_at=%s WHERE session_id=%s",
            (row["current_item_id"], row["current_item_set_at"], session_id),
        )
    conn.execute(
        "UPDATE harness_sessions SET current_item_id=%s, current_item_set_at=%s WHERE session_id=%s",
        (item_id, _now_iso(), session_id),
    )


def _clear_current_item(conn, session_id: str) -> None:
    """Move current focus to recent and clear current_item_* fields."""
    row = query_one(
        conn,
        "SELECT current_item_id, current_item_set_at FROM harness_sessions WHERE session_id=%s",
        (session_id,),
    )
    if row is None:
        return
    if row["current_item_id"]:
        conn.execute(
            "UPDATE harness_sessions SET recent_item_id=%s, recent_item_recorded_at=%s WHERE session_id=%s",
            (row["current_item_id"], row["current_item_set_at"], session_id),
        )
    conn.execute(
        "UPDATE harness_sessions SET current_item_id=NULL, current_item_set_at=NULL WHERE session_id=%s",
        (session_id,),
    )


def _require_active_session(conn, session_id: str) -> None:
    row = query_one(
        conn,
        "SELECT COUNT(*) as cnt, COALESCE(MAX(ended_at), '') as ended "
        "FROM harness_sessions WHERE session_id=%s",
        (session_id,),
    )
    if not row or row["cnt"] == 0:
        raise LookupError(f"session '{session_id}' not found")
    if row["ended"]:
        raise PermissionError(f"session '{session_id}' has already ended")
