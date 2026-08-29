"""Serialize item-bound preview environments with item lifecycle changes."""

from __future__ import annotations

from typing import Any, Optional

from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import iso8601_now
from yoke_core.domain.project_identity import render_item_ref, resolve_item_id
from yoke_core.domain.schema_common import _table_exists
from yoke_core.domain.workflow_item_binding_lock import (
    lock_item_workflow_bindings,
)
from yoke_core.domain.workflow_item_binding_validation import (
    item_binding_runtime_state,
)

INACTIVE_ENVIRONMENT_STATUSES = frozenset({"failed", "stopped"})


def _marker(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _for_update(conn: Any) -> str:
    return " FOR UPDATE" if db_backend.connection_is_postgres(conn) else ""


def _row_value(row: Any, name: str, index: int) -> Any:
    return row[name] if hasattr(row, "keys") else row[index]


def _resolve_bound_item(
    conn: Any,
    public_ref: str,
    *,
    project: str,
) -> int:
    item_id = resolve_item_id(conn, public_ref, project=project)
    if item_id is None:
        raise ValueError(
            f"ephemeral environment item {public_ref!r} does not resolve "
            f"in project {project!r}"
        )
    return int(item_id)


def prepare_create_item_binding(
    conn: Any,
    *,
    public_ref: str,
    project: str,
    branch: str,
) -> str:
    """Lock and canonicalize an active environment's optional item binding."""
    clean_ref = str(public_ref or "").strip()
    if not clean_ref:
        marker = _marker(conn)
        row = conn.execute(
            "SELECT ee.item FROM ephemeral_environments ee "
            "JOIN projects p ON p.id=ee.project_id "
            f"WHERE p.slug={marker} AND ee.branch={marker}",
            (project, branch),
        ).fetchone()
        clean_ref = str(_row_value(row, "item", 0) or "") if row is not None else ""
        if not clean_ref:
            return ""
    item_id = _resolve_bound_item(conn, clean_ref, project=project)
    lock_item_workflow_bindings(conn, (item_id,))
    item_binding_runtime_state(conn, item_id)
    return render_item_ref(conn, item_id)


def prepare_update_item_binding(
    conn: Any,
    *,
    env_id: int,
    field: str,
    value: str,
) -> str:
    """Guard updates that bind or reactivate an item-owned environment."""
    marker = _marker(conn)
    snapshot = conn.execute(
        "SELECT ee.item, ee.status, p.slug "
        "FROM ephemeral_environments ee "
        "JOIN projects p ON p.id=ee.project_id "
        f"WHERE ee.id={marker}",
        (int(env_id),),
    ).fetchone()
    if snapshot is None:
        raise LookupError(f"ephemeral environment '{env_id}' not found")
    old_ref = str(_row_value(snapshot, "item", 0) or "")
    old_status = str(_row_value(snapshot, "status", 1) or "")
    project = str(_row_value(snapshot, "slug", 2))

    binding_ref: Optional[str] = None
    if field == "status" and value not in INACTIVE_ENVIRONMENT_STATUSES:
        binding_ref = old_ref
    elif field == "item" and old_status not in INACTIVE_ENVIRONMENT_STATUSES:
        binding_ref = value
    if not binding_ref:
        return value

    item_id = _resolve_bound_item(conn, binding_ref, project=project)
    lock_item_workflow_bindings(conn, (item_id,))
    item_binding_runtime_state(conn, item_id)
    locked = conn.execute(
        "SELECT item, status FROM ephemeral_environments "
        f"WHERE id={marker}{_for_update(conn)}",
        (int(env_id),),
    ).fetchone()
    if locked is None:
        raise LookupError(f"ephemeral environment '{env_id}' not found")
    if (
        str(_row_value(locked, "item", 0) or "") != old_ref
        or str(_row_value(locked, "status", 1) or "") != old_status
    ):
        raise RuntimeError(
            f"ephemeral environment {env_id} binding changed concurrently; retry"
        )
    return render_item_ref(conn, item_id) if field == "item" else value


def stop_item_environments(conn: Any, *, item_id: int) -> int:
    """Stop every active preview label associated with one locked item."""
    if not _table_exists(conn, "ephemeral_environments"):
        return 0
    marker = _marker(conn)
    item = conn.execute(
        f"SELECT project_id FROM items WHERE id={marker}",
        (int(item_id),),
    ).fetchone()
    if item is None:
        raise ValueError(f"item {item_id} does not exist")
    project_id = int(_row_value(item, "project_id", 0))
    labels = tuple(
        sorted(
            {
                render_item_ref(conn, int(item_id)),
                f"YOK-{int(item_id)}",
                str(int(item_id)),
            }
        )
    )
    placeholders = ", ".join(marker for _ in labels)
    status_placeholders = ", ".join(marker for _ in INACTIVE_ENVIRONMENT_STATUSES)
    cursor = conn.execute(
        "UPDATE ephemeral_environments SET status='stopped', "
        f"stopped_at={marker} WHERE project_id={marker} "
        f"AND item IN ({placeholders}) "
        f"AND status NOT IN ({status_placeholders})",
        (
            iso8601_now(),
            project_id,
            *labels,
            *sorted(INACTIVE_ENVIRONMENT_STATUSES),
        ),
    )
    return max(int(cursor.rowcount or 0), 0)


__all__ = [
    "INACTIVE_ENVIRONMENT_STATUSES",
    "prepare_create_item_binding",
    "prepare_update_item_binding",
    "stop_item_environments",
]
