"""Final compare-and-lock boundary for workflow-sensitive status writes."""

from __future__ import annotations

from typing import Any, Optional

from yoke_core.domain import db_backend
from yoke_core.domain.backlog_item_db_writes import _update_item_multi
from yoke_core.domain.project_identity import render_item_ref
from yoke_core.domain.workflow_item_binding_lock import (
    lock_item_workflow_bindings,
)


WORKFLOW_STATUS_PRECONDITION_FAILED = "WORKFLOW_STATUS_PRECONDITION_FAILED"


def lock_status_write_precondition(
    conn: Any,
    *,
    item_id: int,
    observed_status: str,
    observed_workflow_version_id: int,
    expected_status: Optional[str],
    expected_workflow_version_id: Optional[int],
) -> Optional[dict[str, Any]]:
    """Lock the item and reject validation performed against stale state."""
    lock_item_workflow_bindings(conn, (int(item_id),))
    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    row = conn.execute(
        f"SELECT status, workflow_version_id FROM items WHERE id = {marker}",
        (int(item_id),),
    ).fetchone()
    if row is None:
        public_ref = render_item_ref(conn, int(item_id))
        conn.rollback()
        return {
            "success": False,
            "error": f"Item {public_ref} no longer exists",
            "error_code": WORKFLOW_STATUS_PRECONDITION_FAILED,
        }
    live_status = str(row["status"] if hasattr(row, "keys") else row[0])
    live_version = int(row["workflow_version_id"] if hasattr(row, "keys") else row[1])
    required_status = (
        str(expected_status) if expected_status is not None else observed_status
    )
    required_version = (
        int(expected_workflow_version_id)
        if expected_workflow_version_id is not None
        else int(observed_workflow_version_id)
    )
    if live_status == required_status and live_version == required_version:
        return None
    conn.rollback()
    return {
        "success": False,
        "error": (
            "workflow/status changed while transition gates were evaluated; "
            f"expected status={required_status!r}, workflow_version_id="
            f"{required_version}; found status={live_status!r}, "
            f"workflow_version_id={live_version}"
        ),
        "error_code": WORKFLOW_STATUS_PRECONDITION_FAILED,
    }


def apply_prepared_item_writes(
    conn: Any,
    *,
    item_id: int,
    field: str,
    value: str,
    item: dict[str, Any],
    field_writes: dict[str, Any],
    expected_status: Optional[str],
    expected_workflow_version_id: Optional[int],
) -> Optional[dict[str, Any]]:
    """Apply prepared writes behind the final workflow/status comparison."""
    filtered = {
        key: field_value
        for key, field_value in field_writes.items()
        if key != "updated_at"
    }
    if filtered:
        if field == "status":
            stale = lock_status_write_precondition(
                conn,
                item_id=item_id,
                observed_status=str(item["status"]),
                observed_workflow_version_id=int(item["workflow_version_id"]),
                expected_status=expected_status,
                expected_workflow_version_id=expected_workflow_version_id,
            )
            if stale is not None:
                return stale
        _update_item_multi(
            conn,
            item_id,
            filtered,
            commit=field != "status",
        )
    return None


__all__ = [
    "WORKFLOW_STATUS_PRECONDITION_FAILED",
    "apply_prepared_item_writes",
    "lock_status_write_precondition",
]
