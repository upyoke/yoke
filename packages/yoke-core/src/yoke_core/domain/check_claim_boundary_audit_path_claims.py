"""Path-claim helpers for the claim-boundary audit."""

from __future__ import annotations

import json
from typing import Any, Optional

from yoke_core.domain.schema_common import (
    _column_exists as _schema_column_exists,
    _table_exists as _schema_table_exists,
)


def _coerce_int(value: Any) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(str(value).replace("YOK-", ""))
    except (ValueError, TypeError):
        return None


def _context(row: Any) -> dict:
    raw = row["envelope"]
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError, ValueError):
        return {}
    if not isinstance(parsed, dict):
        return {}
    ctx = parsed.get("context", {})
    return ctx if isinstance(ctx, dict) else {}


def path_claim_event_has_matching_item_owner(
    conn: Any,
    row: Any,
    *,
    item_id: int,
) -> bool:
    """Return true when a PathClaimAmended event names this item-owned claim."""
    claim_id = _coerce_int(_context(row).get("claim_id"))
    if claim_id is None:
        return False
    if not _schema_table_exists(conn, "path_claims"):
        return False
    if not _schema_column_exists(conn, "path_claims", "owner_kind"):
        return False
    if not _schema_column_exists(conn, "path_claims", "owner_item_id"):
        return False

    from yoke_core.domain import db_backend

    p = "%s" if db_backend.connection_is_postgres(conn) else "?"
    claim_row = conn.execute(
        f"""
        SELECT owner_kind, owner_item_id
        FROM path_claims
        WHERE id={p}
        """,
        (claim_id,),
    ).fetchone()
    if claim_row is None:
        return False
    return claim_row["owner_kind"] == "item" and (
        _coerce_int(claim_row["owner_item_id"]) == item_id
    )


__all__ = ("path_claim_event_has_matching_item_owner",)
