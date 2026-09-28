"""Distinguish a post-merge status change from a stale merge-time status."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping

from yoke_core.domain import db_backend
from yoke_core.domain.schema_common import _table_exists


def _instant(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed


def items_returned_after_landing(
    conn: Any, items: Mapping[int, Mapping[str, Any]]
) -> set[int]:
    """Find current item statuses recorded after their latest merge stamp.

    The transition table is lifecycle state, unlike disposable events. A
    current status with no later item-level transition retains the usual
    closeout projection for a merge that left its old status behind.
    """
    landed = {
        item_id: max(
            (
                stamp
                for stamp in (
                    _instant(item.get("merged_at")),
                    _instant(item.get("merge_queue_landed_at")),
                )
                if stamp is not None
            ),
            default=None,
        )
        for item_id, item in items.items()
    }
    landed = {item_id: stamp for item_id, stamp in landed.items() if stamp}
    if not landed or not _table_exists(conn, "item_status_transitions"):
        return set()
    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    records = conn.execute(
        "SELECT t.item_id,t.to_status,t.created_at "
        "FROM item_status_transitions t JOIN ("
        "SELECT item_id,MAX(id) AS id FROM item_status_transitions "
        "WHERE task_num IS NULL AND item_id IN ("
        + ",".join(marker for _ in landed)
        + ") GROUP BY item_id) latest ON latest.id=t.id",
        tuple(landed),
    ).fetchall()
    returned: set[int] = set()
    for row in records:
        item_id = int(row["item_id"])
        transition_time = _instant(row["created_at"])
        if (
            transition_time is not None
            and transition_time > landed[item_id]
            and str(row["to_status"]) == str(items[item_id]["status"])
        ):
            returned.add(item_id)
    return returned


__all__ = ["items_returned_after_landing"]
