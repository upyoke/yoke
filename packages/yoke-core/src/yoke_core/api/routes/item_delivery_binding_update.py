"""Coupled project/deployment-flow validation for item PATCH writes."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from yoke_core.domain.deployment_flow_validator import (
    normalize_deployment_flow_value,
    validate_and_lookup_flow_project,
)
from yoke_core.domain.project_identity import DEFAULT_PROJECT_SLUG
from yoke_core.domain.workflow_item_binding_lock import (
    lock_item_workflow_bindings,
)


def prospective_project_for_update(
    updates: dict[str, Any],
    item: dict[str, Any],
) -> str:
    """Mirror the write adapter's explicit-empty-to-default normalization."""
    if "project" in updates:
        return str(updates["project"] or DEFAULT_PROJECT_SLUG)
    return str(item.get("project") or DEFAULT_PROJECT_SLUG)


def lock_and_validate_delivery_binding(
    conn: Any,
    *,
    item_id: int,
    updates: dict[str, Any],
    initial_row: Any,
    read_item: Callable[[Any, int], Any],
) -> tuple[Any, str | None, str | None]:
    """Lock and validate the prospective item project/flow pair."""
    if "deployment_flow" in updates:
        updates["deployment_flow"] = normalize_deployment_flow_value(
            updates["deployment_flow"]
        )

    row = initial_row
    observed_flow = (
        updates["deployment_flow"]
        if "deployment_flow" in updates
        else dict(row).get("deployment_flow")
    )
    while True:
        project_hint = prospective_project_for_update(updates, dict(row))
        flow_project, flow_error = validate_and_lookup_flow_project(
            conn,
            observed_flow,
            project_hint,
            lock_binding=bool(observed_flow),
        )
        lock_item_workflow_bindings(conn, (int(item_id),))
        locked_row = read_item(conn, item_id)
        if locked_row is None:
            return None, None, None

        locked_item = dict(locked_row)
        prospective_flow = (
            updates["deployment_flow"]
            if "deployment_flow" in updates
            else locked_item.get("deployment_flow")
        )
        if prospective_flow != observed_flow:
            # Release the stale flow lock and retry in flow-then-item order.
            conn.rollback()
            row = locked_row
            observed_flow = prospective_flow
            continue

        prospective_project = prospective_project_for_update(updates, locked_item)
        if flow_error:
            return locked_row, None, flow_error
        if flow_project and flow_project != prospective_project:
            return (
                locked_row,
                flow_project,
                (
                    f"Deployment flow '{prospective_flow}' belongs to project "
                    f"'{flow_project}', but the prospective item project is "
                    f"'{prospective_project}'."
                ),
            )
        return locked_row, flow_project, None


__all__ = [
    "lock_and_validate_delivery_binding",
    "prospective_project_for_update",
]
