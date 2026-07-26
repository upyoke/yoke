"""Workflow registry setup shared by API fixture builders."""

from __future__ import annotations

from yoke_core.domain.workflow_registry import (
    converge_builtin_workflows,
    resolve_current_workflow_pin,
)
from yoke_core.domain.workflow_schema import ensure_workflow_schema


def install_workflow_registry_and_pin_items(
    conn,
    *,
    default_workflow_id: str = "issue",
    workflow_id_by_item: dict[int, str] | None = None,
) -> None:
    """Converge built-ins and complete explicit fixture workflow pins."""
    ensure_workflow_schema(conn)
    converge_builtin_workflows(conn)
    assignments = workflow_id_by_item or {}
    for item_id, workflow_id in assignments.items():
        resolved_id, version_id = resolve_current_workflow_pin(
            conn,
            workflow_id,
        )
        conn.execute(
            "UPDATE items SET workflow_id = %s, workflow_version_id = %s "
            "WHERE id = %s",
            (resolved_id, version_id, item_id),
        )
    resolved_id, version_id = resolve_current_workflow_pin(
        conn,
        default_workflow_id,
    )
    conn.execute(
        "UPDATE items SET workflow_id = %s, workflow_version_id = %s "
        "WHERE workflow_id IS NULL AND workflow_version_id IS NULL",
        (resolved_id, version_id),
    )
    conn.commit()


__all__ = ["install_workflow_registry_and_pin_items"]
