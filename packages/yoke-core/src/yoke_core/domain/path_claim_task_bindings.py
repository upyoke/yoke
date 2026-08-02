"""Durable task scope for item-owned path claims.

An Epic path claim stays item-owned.  This table records which generated
tasks may consume that coverage without turning a transient work claim or
registering session into path authority.
"""

from __future__ import annotations

from typing import Any

from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import iso8601_now
from yoke_core.domain.project_identity import render_item_ref
from yoke_core.domain.schema_common import _column_exists, _table_exists
from yoke_core.domain.workflow_item_binding_lock import (
    lock_optional_item_workflow_binding,
)
from yoke_core.domain.workflow_effective_policies import (
    load_item_effective_workflow_policies,
)


REQUIRED_PER_TASK = "required_per_task"
NON_TERMINAL_CLAIM_STATES = ("planned", "blocked", "active")


class PathClaimTaskBindingError(ValueError):
    """A claim cannot be attached to the requested Epic task."""


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _value(row: Any, key: str, position: int) -> Any:
    return row[key] if hasattr(row, "keys") else row[position]


def validate_task_binding_target(
    conn: Any,
    *,
    item_id: int,
    task_num: int,
) -> None:
    """Lock and validate the item pin and generated task before mutation."""
    locked = lock_optional_item_workflow_binding(conn, int(item_id))
    if locked and int(item_id) not in locked:
        raise PathClaimTaskBindingError(f"item {item_id} does not exist")
    effective = load_item_effective_workflow_policies(conn, int(item_id))
    runtime = effective.runtime
    if effective.path_claims != REQUIRED_PER_TASK:
        raise PathClaimTaskBindingError(
            f"workflow {runtime.workflow_id}@{runtime.version} does not use "
            "task-scoped path claims"
        )
    if str(runtime.policies["generated_children"]) != "epic_tasks":
        raise PathClaimTaskBindingError(
            f"workflow {runtime.workflow_id}@{runtime.version} does not "
            "generate Epic tasks"
        )
    marker = _p(conn)
    suffix = " FOR UPDATE" if db_backend.connection_is_postgres(conn) else ""
    row = conn.execute(
        "SELECT task_num FROM epic_tasks "
        f"WHERE epic_id = {marker} AND task_num = {marker}{suffix}",
        (int(item_id), int(task_num)),
    ).fetchone()
    if row is None:
        raise PathClaimTaskBindingError(
            f"Epic task {item_id}/{task_num} does not exist"
        )


def item_uses_task_scoped_claims(conn: Any, item_id: int) -> bool:
    """Whether the item's immutable workflow pin requires per-task scope."""
    effective = load_item_effective_workflow_policies(conn, int(item_id))
    return effective.path_claims == REQUIRED_PER_TASK


def pinned_task_claim_policy(conn: Any, item_id: int) -> bool | None:
    """Return task-scope policy, or ``None`` for a genuinely legacy fixture."""
    if not (
        _table_exists(conn, "items")
        and _table_exists(conn, "workflow_versions")
        and _column_exists(conn, "items", "workflow_version_id")
    ):
        return None
    row = conn.execute(
        f"SELECT workflow_version_id FROM items WHERE id = {_p(conn)}",
        (int(item_id),),
    ).fetchone()
    if row is None or _value(row, "workflow_version_id", 0) is None:
        return None
    return item_uses_task_scoped_claims(conn, int(item_id))


def bind_claim_to_task(
    conn: Any,
    *,
    claim_id: int,
    item_id: int,
    task_num: int,
    commit: bool = True,
) -> None:
    """Attach an item-owned claim to a task, idempotently."""
    validate_task_binding_target(
        conn,
        item_id=int(item_id),
        task_num=int(task_num),
    )
    marker = _p(conn)
    claim = conn.execute(
        "SELECT id, owner_kind, owner_item_id "
        f"FROM path_claims WHERE id = {marker}",
        (int(claim_id),),
    ).fetchone()
    if claim is None:
        raise PathClaimTaskBindingError(f"path claim {claim_id} does not exist")
    owner_kind = _value(claim, "owner_kind", 1)
    owner_item = _value(claim, "owner_item_id", 2)
    if owner_kind != "item" or int(owner_item or -1) != int(item_id):
        raise PathClaimTaskBindingError(
            f"path claim {claim_id} is not item-owned by "
            f"{render_item_ref(conn, int(item_id))}"
        )
    conn.execute(
        "INSERT INTO path_claim_task_bindings "
        "(claim_id, epic_id, task_num, bound_at) "
        f"VALUES ({marker}, {marker}, {marker}, {marker}) "
        "ON CONFLICT (claim_id, epic_id, task_num) DO NOTHING",
        (int(claim_id), int(item_id), int(task_num), iso8601_now()),
    )
    if commit:
        conn.commit()


def task_bindings_for_claim(conn: Any, claim_id: int) -> list[dict[str, Any]]:
    """Return stable task-scope projections for one claim."""
    if not _table_exists(conn, "path_claim_task_bindings"):
        return []
    rows = conn.execute(
        "SELECT epic_id, task_num, bound_at "
        f"FROM path_claim_task_bindings WHERE claim_id = {_p(conn)} "
        "ORDER BY epic_id, task_num",
        (int(claim_id),),
    ).fetchall()
    return [
        {
            "epic_id": int(_value(row, "epic_id", 0)),
            "task_num": int(_value(row, "task_num", 1)),
            "bound_at": str(_value(row, "bound_at", 2)),
        }
        for row in rows
    ]


def delete_task_bindings(
    conn: Any,
    *,
    item_id: int,
    task_num: int,
    commit: bool = False,
) -> None:
    """Remove task scope before deleting or replacing its generated row."""
    if not _table_exists(conn, "path_claim_task_bindings"):
        return
    marker = _p(conn)
    conn.execute(
        "DELETE FROM path_claim_task_bindings "
        f"WHERE epic_id = {marker} AND task_num = {marker}",
        (int(item_id), int(task_num)),
    )
    if commit:
        conn.commit()


__all__ = [
    "NON_TERMINAL_CLAIM_STATES",
    "PathClaimTaskBindingError",
    "REQUIRED_PER_TASK",
    "bind_claim_to_task",
    "delete_task_bindings",
    "item_uses_task_scoped_claims",
    "pinned_task_claim_policy",
    "task_bindings_for_claim",
    "validate_task_binding_target",
]
