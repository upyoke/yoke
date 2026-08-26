"""Read-only claim facts shared by item roster and detail projections."""

from __future__ import annotations

from typing import Any, Iterable

from yoke_core.domain import db_backend
from yoke_core.domain.actor_display import actor_display_name
from yoke_core.domain.actors import ActorError
from yoke_core.domain.schema_common import _table_exists
from yoke_core.domain.work_claim_targets import scope_int_sql


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _dict_rows(cursor: Any) -> list[dict[str, Any]]:
    columns = [str(column[0]) for column in cursor.description]
    return [
        dict(row) if hasattr(row, "keys") else dict(zip(columns, row))
        for row in cursor.fetchall()
    ]


def _claim_label(conn: Any, row: dict[str, Any]) -> str:
    actor_id = row.get("actor_id")
    if actor_id is not None:
        try:
            return actor_display_name(conn, int(actor_id))
        except ActorError:
            pass
    return str(row.get("executor") or row.get("session_id") or "")


def active_item_claims(
    conn: Any,
    item_ids: Iterable[int],
) -> dict[int, dict[str, Any]]:
    """Return the newest active item claim for each requested item."""
    ids = sorted({int(item_id) for item_id in item_ids})
    if not ids or not _table_exists(conn, "work_claims"):
        return {}
    marker = _p(conn)
    placeholders = ", ".join(marker for _ in ids)
    item_scope = scope_int_sql(conn, "wc.scope", "item_id")
    newer_item_scope = scope_int_sql(conn, "newer.scope", "item_id")
    cursor = conn.execute(
        f"SELECT {item_scope} AS item_id, wc.id AS claim_id, wc.session_id, "
        "wc.claim_type, wc.claimed_at, hs.actor_id, hs.executor, "
        "a.kind AS actor_kind "
        "FROM work_claims wc "
        "LEFT JOIN harness_sessions hs ON hs.session_id = wc.session_id "
        "LEFT JOIN actors a ON a.id = hs.actor_id "
        f"WHERE {item_scope} IN ({placeholders}) "
        "AND wc.target_kind = 'item' AND wc.released_at IS NULL "
        "AND NOT EXISTS ("
        "  SELECT 1 FROM work_claims newer "
        f"  WHERE {newer_item_scope} = {item_scope} "
        "  AND newer.target_kind = 'item' "
        "  AND newer.released_at IS NULL AND newer.id > wc.id"
        f") ORDER BY {item_scope}",
        tuple(ids),
    )
    claims: dict[int, dict[str, Any]] = {}
    for row in _dict_rows(cursor):
        item_id = int(row["item_id"])
        claims[item_id] = {
            "claim_id": int(row["claim_id"]),
            "session_id": str(row.get("session_id") or ""),
            "claim_type": str(row.get("claim_type") or ""),
            "claimed_at": row.get("claimed_at"),
            "actor_id": (
                int(row["actor_id"]) if row.get("actor_id") is not None else None
            ),
            "actor_kind": row.get("actor_kind"),
            "actor_label": _claim_label(conn, row),
            "executor": row.get("executor"),
        }
    return claims


__all__ = ["active_item_claims"]
