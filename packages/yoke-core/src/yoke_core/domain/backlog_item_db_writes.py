"""Backlog item DB writes — the low-level INSERT and UPDATE helpers
used by ``execute_create``, ``execute_update``, and the cancellation
path. Each helper keeps the connection's commit semantics local.
"""

from __future__ import annotations

import json
from typing import Any, Optional

from yoke_core.domain.backlog_queries import (
    INTEGER_FIELDS,
    _now_iso,
)
from yoke_core.domain.deployment_flow_validator import (
    require_flow_for_item_binding,
)
from yoke_core.domain.project_identity import resolve_project_id
from yoke_core.domain import workflow_item_binding_lock


def _insert_item(
    conn: Any,
    item_id: int,
    title: str,
    status: str,
    priority: str,
    frozen: int,
    github_issue: Optional[str],
    deployed_to: Optional[str],
    body: Optional[str],
    created_at: str,
    updated_at: str,
    source: str,
    project_id: int,
    project_sequence: int,
    deployment_flow: Optional[str],
    *,
    workflow_id: str,
    workflow_version_id: int,
    owner: Optional[str] = None,
    instruction: Optional[str] = None,
    workflow_posture: Optional[dict[str, Any]] = None,
    commit: bool = True,
) -> None:
    """Insert a new item into the DB. The body param is accepted but ignored.

    ``source`` is the stringified ``actors.id`` of the actor that
    declared the item; ``owner`` is the same projection for the actor
    accountable for the work, defaulting to ``source`` when callers do
    not pass it. The migration backfills both columns and the writer
    keeps them in lockstep going forward.
    """
    require_flow_for_item_binding(conn, deployment_flow)
    owner_value = owner if owner is not None else source
    conn.execute(
        """INSERT INTO items (
            id, title, status, priority,
            frozen,
            github_issue, deployed_to,
            created_at, updated_at, source, owner,
            project_id, project_sequence, deployment_flow,
            workflow_id, workflow_version_id, workflow_posture,
            spec, spec_updated_at, spec_updated_by
        ) VALUES (
            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
        )""",
        (
            item_id,
            title,
            status,
            priority,
            frozen,
            github_issue,
            deployed_to,
            created_at,
            updated_at,
            source,
            owner_value,
            project_id,
            project_sequence,
            deployment_flow,
            workflow_id,
            workflow_version_id,
            json.dumps(workflow_posture or {}, sort_keys=True),
            instruction,
            updated_at if instruction else None,
            source if instruction else None,
        ),
    )
    if commit:
        conn.commit()


@workflow_item_binding_lock.rollback_workflow_binding_write_errors
def _update_item_field(
    conn: Any,
    item_id: int,
    field: str,
    value: Any,
) -> None:
    """Update a single field on an item.

    Handles type coercion: None -> NULL, bool -> int, etc.
    """
    now = _now_iso()
    if field == "deployment_flow":
        require_flow_for_item_binding(conn, value)
        workflow_item_binding_lock.lock_item_workflow_bindings(conn, (item_id,))
    if field == "project":
        field = "project_id"
        value = resolve_project_id(conn, value)

    if value is None:
        conn.execute(
            f"UPDATE items SET {field} = NULL, updated_at = %s WHERE id = %s",
            (now, item_id),
        )
    elif field in INTEGER_FIELDS:
        if field in ("frozen", "blocked") and isinstance(value, str):
            int_val = 1 if value.lower() == "true" else 0
        else:
            int_val = int(value) if value is not None else 0
        conn.execute(
            f"UPDATE items SET {field} = %s, updated_at = %s WHERE id = %s",
            (int_val, now, item_id),
        )
    elif isinstance(value, bool):
        conn.execute(
            f"UPDATE items SET {field} = %s, updated_at = %s WHERE id = %s",
            (1 if value else 0, now, item_id),
        )
    else:
        conn.execute(
            f"UPDATE items SET {field} = %s, updated_at = %s WHERE id = %s",
            (str(value), now, item_id),
        )
    conn.commit()


@workflow_item_binding_lock.rollback_workflow_binding_write_errors
def _update_item_multi(
    conn: Any,
    item_id: int,
    field_writes: dict[str, Any],
    *,
    commit: bool = True,
) -> None:
    """Apply multiple field writes, optionally inside a caller transaction."""
    if "deployment_flow" in field_writes:
        require_flow_for_item_binding(conn, field_writes["deployment_flow"])
        workflow_item_binding_lock.lock_item_workflow_bindings(conn, (int(item_id),))
    now = _now_iso()
    sets = []
    params: list[Any] = []

    for field, value in field_writes.items():
        if field == "updated_at":
            continue
        if field == "project":
            field = "project_id"
            value = resolve_project_id(conn, value)
        if value is None:
            sets.append(f"{field} = NULL")
        elif (
            field in INTEGER_FIELDS
            or field in ("frozen", "blocked")
            or isinstance(value, bool)
        ):
            sets.append(f"{field} = %s")
            if isinstance(value, bool):
                params.append(1 if value else 0)
            elif field in ("frozen", "blocked") and isinstance(value, str):
                params.append(1 if value.lower() == "true" else 0)
            else:
                params.append(int(value))
        else:
            sets.append(f"{field} = %s")
            params.append(str(value))

    if not sets:
        return

    sets.append("updated_at = %s")
    params.append(now)
    params.append(item_id)

    sql = f"UPDATE items SET {', '.join(sets)} WHERE id = %s"
    conn.execute(sql, tuple(params))
    if commit:
        conn.commit()


__all__ = ["_insert_item", "_update_item_field", "_update_item_multi"]
