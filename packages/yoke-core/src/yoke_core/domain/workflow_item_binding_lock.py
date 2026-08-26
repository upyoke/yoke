"""Transaction lock shared by item workflow migration and binding writers."""

from __future__ import annotations

from collections.abc import Iterable
from functools import wraps
from typing import Any

from yoke_core.domain import db_backend
from yoke_core.domain.schema_common import _column_exists, _table_exists
from yoke_core.domain.work_claim_targets import scope_int_sql


def rollback_workflow_binding_write_errors(function: Any) -> Any:
    """Roll back an owning writer, preserving caller-owned transactions.

    Writers expose ``commit=False`` when their mutation participates in a
    larger transaction. In that mode an exception must reach the owner
    without rolling back unrelated writes behind its back.
    """

    @wraps(function)
    def guarded(conn: Any, *args: Any, **kwargs: Any) -> Any:
        try:
            return function(conn, *args, **kwargs)
        except Exception:
            if kwargs.get("commit", True):
                conn.rollback()
            raise

    return guarded


def lock_item_workflow_bindings(
    conn: Any,
    item_ids: Iterable[int],
) -> tuple[int, ...]:
    """Lock item rows in stable order for workflow-sensitive binding writes.

    The caller owns the surrounding transaction and must commit or roll back.
    PostgreSQL's row lock supplies the production serialization boundary.
    Missing parent rows and compatibility fixtures without ``items`` are
    ignored because they cannot be workflow-migration targets. SQLite keeps
    the same best-effort parent lookup while relying on database-level write
    serialization.
    """
    normalized = tuple(sorted({int(item_id) for item_id in item_ids}))
    if not normalized or not _table_exists(conn, "items"):
        return ()
    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    placeholders = ", ".join(marker for _ in normalized)
    suffix = " FOR UPDATE" if db_backend.connection_is_postgres(conn) else ""
    rows = conn.execute(
        f"SELECT id FROM items WHERE id IN ({placeholders}) ORDER BY id{suffix}",
        normalized,
    ).fetchall()
    found = tuple(
        int(row["id"]) if hasattr(row, "keys") else int(row[0]) for row in rows
    )
    return found


def lock_optional_item_workflow_binding(
    conn: Any,
    item_id: int | None,
) -> tuple[int, ...]:
    """Lock one parent item when the binding carries an item reference."""
    return lock_item_workflow_bindings(
        conn,
        () if item_id is None else (int(item_id),),
    )


def lock_path_claim_workflow_binding(
    conn: Any,
    claim_id: int,
) -> tuple[int, ...]:
    """Lock the item owner of one path claim, when it has one."""
    if not _table_exists(conn, "path_claims"):
        return ()
    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    item_expression = "CASE WHEN owner_kind = 'item' THEN owner_item_id ELSE NULL END"
    row = conn.execute(
        f"SELECT {item_expression} AS item_id FROM path_claims WHERE id = {marker}",
        (int(claim_id),),
    ).fetchone()
    if row is None:
        return ()
    item_id = row["item_id"] if hasattr(row, "keys") else row[0]
    return lock_optional_item_workflow_binding(conn, item_id)


def lock_work_claim_target_workflow_binding(
    conn: Any,
    target: Any,
) -> tuple[int, ...]:
    """Lock the item or epic parent carried by one typed work target."""
    item_id = getattr(target, "item_id", None)
    if item_id is None:
        item_id = getattr(target, "epic_id", None)
    return lock_optional_item_workflow_binding(conn, item_id)


def lock_work_claims_workflow_bindings(
    conn: Any,
    claim_ids: Iterable[int],
) -> tuple[int, ...]:
    """Lock item or epic parents carried by persisted work claims."""
    normalized = tuple(sorted({int(claim_id) for claim_id in claim_ids}))
    if not normalized or not _table_exists(conn, "work_claims"):
        return ()
    if not _column_exists(conn, "work_claims", "scope"):
        return ()
    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    placeholders = ", ".join(marker for _ in normalized)
    item_scope = scope_int_sql(conn, "scope", "item_id")
    epic_scope = scope_int_sql(conn, "scope", "epic_id")
    item_expression = (
        f"CASE WHEN target_kind = 'item' THEN {item_scope} "
        f"WHEN target_kind = 'epic_task' THEN {epic_scope} ELSE NULL END"
    )
    rows = conn.execute(
        f"SELECT {item_expression} AS item_id FROM work_claims "
        f"WHERE id IN ({placeholders}) ORDER BY id",
        normalized,
    ).fetchall()
    locked_items = lock_item_workflow_bindings(
        conn,
        (
            row["item_id"] if hasattr(row, "keys") else row[0]
            for row in rows
            if (row["item_id"] if hasattr(row, "keys") else row[0]) is not None
        ),
    )
    suffix = " FOR UPDATE" if db_backend.connection_is_postgres(conn) else ""
    conn.execute(
        f"SELECT id FROM work_claims WHERE id IN ({placeholders}) ORDER BY id{suffix}",
        normalized,
    ).fetchall()
    return locked_items


__all__ = [
    "lock_item_workflow_bindings",
    "lock_optional_item_workflow_binding",
    "lock_path_claim_workflow_binding",
    "lock_work_claim_target_workflow_binding",
    "lock_work_claims_workflow_bindings",
    "rollback_workflow_binding_write_errors",
]
