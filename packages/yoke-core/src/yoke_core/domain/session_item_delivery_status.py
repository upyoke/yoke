"""The release a session's held item is riding, for the fleet roster.

A session card already says where its item is in its own workflow. It could
not say where that item is in the release carrying it, so a worker parked
until a stage deploys looked identical to one parked on a review, and the
only way to tell was to open the run.

This answers the second half from the runs themselves: the newest deployment
run that has the item as a member, with that run's own status and stage. A
session holding an item no release carries answers nothing rather than
guessing — and an item that is a member of nothing is the ordinary case for
work that has not merged yet.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from yoke_core.domain import db_backend
from yoke_core.domain.schema_common import _table_exists
from yoke_core.domain.session_item_stage_states import primary_item_ids


def _marker(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _newest_runs(conn: Any, item_ids: Sequence[int]) -> dict[int, dict[str, Any]]:
    if not item_ids:
        return {}
    if not all(
        _table_exists(conn, name)
        for name in ("deployment_runs", "deployment_run_items")
    ):
        return {}
    marker = _marker(conn)
    placeholders = ", ".join(marker for _ in item_ids)
    rows = conn.execute(
        "SELECT dri.item_id, dr.id, dr.status, dr.current_stage, dr.created_at "
        "FROM deployment_runs dr "
        "JOIN deployment_run_items dri ON dri.run_id = dr.id "
        f"WHERE dri.item_id IN ({placeholders}) "
        "ORDER BY dr.created_at DESC, dr.id DESC",
        tuple(int(value) for value in item_ids),
    ).fetchall()
    newest: dict[int, dict[str, Any]] = {}
    for row in rows:
        item_id = int(row["item_id"])
        # Newest first, so the first row seen for an item is the live one.
        if item_id in newest:
            continue
        newest[item_id] = {
            "run_id": str(row["id"]),
            "status": str(row["status"] or ""),
            "stage": str(row["current_stage"] or ""),
        }
    return newest


def primary_item_delivery_by_session(
    conn: Any, rows: list[dict[str, Any]]
) -> dict[str, Mapping[str, Any]]:
    """Project the release carrying each roster session's primary held item."""
    selected = primary_item_ids(conn, rows)
    newest = _newest_runs(conn, tuple(dict.fromkeys(selected.values())))
    return {
        session_id: newest[item_id]
        for session_id, item_id in selected.items()
        if item_id in newest
    }


__all__ = ["primary_item_delivery_by_session"]
