"""The per-item flag saying its GitHub mirror is currently the compact one.

Set by a compact sync and cleared by a full-body sync, so the repair pass
has a candidate queue to read rather than a scan of telemetry envelopes for
failure markers.
"""

from __future__ import annotations

from typing import Any, Optional

from yoke_core.domain.backlog_github_body_budget import SyncMode


# Compact-pending flag — items.github_body_compact_pending: non-NULL ISO
# timestamp = the item's last successful body sync landed the compact
# mirror. Set by a compact sync, cleared by a full-body sync; the repair
# pass (`backfill-oversized-bodies`) reads it as its candidate queue
# (retired pattern: scanning telemetry envelopes for failure markers).


def record_sync_mode(conn: Optional[Any], item_id: int, mode: SyncMode) -> None:
    """Stamp/clear ``github_body_compact_pending`` after a successful sync.

    Best-effort: minimal fixture DBs without the column are tolerated
    (savepoint keeps the caller's transaction clean). Commits via the
    caller's connection.
    """
    if conn is None:
        return
    from yoke_core.domain import db_backend
    from yoke_core.domain.db_helpers import iso8601_now

    p = "%s" if db_backend.connection_is_postgres(conn) else "?"
    value = iso8601_now() if mode == "compact" else None
    try:
        conn.execute("SAVEPOINT github_body_compact_pending")
        conn.execute(
            f"UPDATE items SET github_body_compact_pending = {p} "
            f"WHERE id = {p}",
            (value, int(item_id)),
        )
        conn.execute("RELEASE SAVEPOINT github_body_compact_pending")
        conn.commit()
    except Exception:
        try:
            conn.execute("ROLLBACK TO SAVEPOINT github_body_compact_pending")
            conn.execute("RELEASE SAVEPOINT github_body_compact_pending")
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass


def list_compact_pending_item_ids(conn: Any) -> list[int]:
    """GitHub-linked items whose mirror is currently the compact fallback."""
    try:
        rows = conn.execute(
            "SELECT id FROM items "
            "WHERE github_body_compact_pending IS NOT NULL "
            "AND github_issue IS NOT NULL AND github_issue <> '' "
            "ORDER BY id"
        ).fetchall()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        return []
    return [int(r[0]) for r in rows]


__all__ = [
    "list_compact_pending_item_ids",
    "record_sync_mode",
]
