"""Exclusive item claim holder lookup shared by staffing surfaces."""

from __future__ import annotations

from typing import Any, Dict

from .db_backend import connection_is_postgres
from .item_ref_resolution import internal_item_key
from .work_claim_targets import scope_int_sql


def _p(conn: Any) -> str:
    return "%s" if connection_is_postgres(conn) else "?"


def holder_session_for_item(conn: Any, item_id: Any) -> Dict[str, Any]:
    """Return the latest active exclusive item claim, or holder_unknown."""
    bare = internal_item_key(conn, item_id)
    if bare is None:
        return {}
    item_scope = scope_int_sql(conn, "scope", "item_id")
    row = conn.execute(
        """SELECT session_id, id, claimed_at, claim_type,
                  {item_scope} AS item_id FROM work_claims
           WHERE target_kind = 'item' AND {item_scope} = {p}
                 AND claim_type = 'exclusive'
                 AND released_at IS NULL
           ORDER BY claimed_at DESC, id DESC LIMIT 1""".format(
            item_scope=item_scope, p=_p(conn)
        ),
        (bare,),
    ).fetchone()
    if row is None:
        return {"holder_unknown": True}
    keys = row.keys() if hasattr(row, "keys") else None
    if keys and "session_id" in keys:
        return {
            "holder_session_id": row["session_id"],
            "claim_id": row["id"],
            "claimed_at": row["claimed_at"],
            "claim_type": row["claim_type"],
            "item_id": row["item_id"],
        }
    return {
        "holder_session_id": row[0],
        "claim_id": row[1],
        "claimed_at": row[2],
        "claim_type": row[3],
        "item_id": row[4],
    }
