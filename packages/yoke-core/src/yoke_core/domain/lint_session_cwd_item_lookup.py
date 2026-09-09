"""Item status and workflow lookups for the session-cwd validator.

Both fail open on a lookup error: a fixture database without the column, or a
schema the running build does not know, must not turn an authority question
into a refusal the caller cannot act on.
"""

from __future__ import annotations

from typing import Any, Optional

from yoke_core.domain import db_backend
from yoke_core.domain.workflow_runtime import (
    WorkflowRuntime,
    load_item_workflow_runtime,
)


def lookup_item_status(
    conn: Any,
    item_id: int,
) -> Optional[str]:
    """Return ``items.status`` for ``item_id`` or ``None`` on lookup miss.

    Fails open on schema mismatch (e.g. test fixtures without a
    ``status`` column) so the new status gate does not regress sessions
    whose authority comes from the existing scope check.
    """
    try:
        p = "%s" if db_backend.connection_is_postgres(conn) else "?"
        row = conn.execute(
            f"SELECT status FROM items WHERE id = {p}",
            (int(item_id),),
        ).fetchone()
    except db_backend.operational_error_types(conn):
        return None
    if row is None:
        return None
    try:
        value = row["status"]
    except (IndexError, KeyError, TypeError):
        value = row[0] if len(row) else None
    if isinstance(value, str):
        return value
    return None


def lookup_item_workflow(
    conn: Any,
    item_id: int,
) -> Optional[WorkflowRuntime]:
    """Return the item's verified workflow pin or fail open on lookup errors."""
    try:
        return load_item_workflow_runtime(conn, int(item_id))
    except Exception:
        return None


__all__ = ["lookup_item_status", "lookup_item_workflow"]
