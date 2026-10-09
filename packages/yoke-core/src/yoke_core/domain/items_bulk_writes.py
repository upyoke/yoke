"""Transactional bulk item updates with declared native clock bindings."""

from typing import Dict, List, Any, Optional

from yoke_core.domain.db_helpers import connect
from yoke_core.domain.item_field_parameters import item_field_parameter
from yoke_core.domain.items_constants import (
    INTEGER_FIELDS,
    _map_frozen_write,
    _map_blocked_write,
    _now_utc,
)
from yoke_core.domain.items_writes_validation import (
    _WORKFLOW_BINDING_FIELDS,
    _reject_workflow_controlled_fields,
)
from yoke_core.domain.deployment_flow_validator import require_flow_for_item_binding
from yoke_core.domain.workflow_item_binding_lock import lock_item_workflow_bindings


def update_item_multi(
    item_id: int,
    pairs: Dict[str, str],
    db_path: Optional[str] = None,
) -> None:
    """Batch-update multiple fields in a single transaction.

    *pairs* is a dict of ``{field: value}`` to set. Automatically sets
    ``updated_at``. Handles frozen boolean mapping, null mapping, and
    integer fields.

    Raises ``ValueError`` for body writes or empty pairs.
    """
    if not pairs:
        raise ValueError("No field=value pairs provided")
    if "body" in pairs:
        raise ValueError(
            "Raw body writes are no longer supported. "
            "items.body is a rendered projection."
        )
    _reject_workflow_controlled_fields(set(pairs))

    now = _now_utc()
    set_clauses: List[str] = []
    params: List[Any] = []

    for field, value in pairs.items():
        set_clauses.append(f"{field} = %s")
        if field == "frozen":
            params.append(_map_frozen_write(value))
        elif field == "blocked":
            params.append(_map_blocked_write(value))
        elif value == "null":
            params.append(None)
        elif field in INTEGER_FIELDS:
            try:
                params.append(int(value))
            except (ValueError, TypeError):
                params.append(None)
        else:
            params.append(value)

    set_clauses.append("updated_at = %s")
    params.append(now)
    params.append(item_id)  # WHERE binding

    sql = f"UPDATE items SET {', '.join(set_clauses)} WHERE id = %s"

    conn = connect(db_path)
    try:
        conn.execute("BEGIN TRANSACTION")
        if set(pairs) & _WORKFLOW_BINDING_FIELDS:
            require_flow_for_item_binding(conn, pairs["deployment_flow"])
            lock_item_workflow_bindings(conn, (int(item_id),))
        params = [
            item_field_parameter(conn, field, value)
            for field, value in zip([*pairs, "updated_at"], params[:-1])
        ] + [item_id]
        conn.execute(sql, tuple(params))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
