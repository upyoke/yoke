"""Pinned completion and flag state for item flag operations."""

from __future__ import annotations
from typing import Any, Dict, Optional


def _cell(row: Any, index: int, name: str) -> Any:
    """Read one column from a tuple row or a mapping row."""
    return row[name] if hasattr(row, "keys") else row[index]


def _load_state(item_id: int) -> Optional[Dict[str, Any]]:
    """Return the item's ref plus its current status and flag values."""
    from yoke_core.domain import db_helpers
    from yoke_core.domain.project_identity import render_item_ref
    from yoke_core.domain.workflow_runtime import load_item_workflow_runtime

    with db_helpers.connect() as conn:
        from yoke_core.domain import db_backend

        marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
        row = conn.execute(
            "SELECT status, frozen, blocked, blocked_reason FROM items "
            f"WHERE id = {marker}",
            (int(item_id),),
        ).fetchone()
        if row is None:
            return None
        return {
            "completed": str(_cell(row, 0, "status") or "")
            in load_item_workflow_runtime(conn, int(item_id)).terminal_stage_ids,
            "public_ref": render_item_ref(conn, int(item_id)),
            "status": str(_cell(row, 0, "status") or ""),
            "frozen": bool(_cell(row, 1, "frozen")),
            "blocked": bool(_cell(row, 2, "blocked")),
            "blocked_reason": _cell(row, 3, "blocked_reason"),
        }
