"""Workflow registry setup shared by API fixture builders."""

from __future__ import annotations

from yoke_core.domain.workflow_registry import (
    converge_builtin_workflows,
    resolve_current_workflow_pin,
)
from yoke_core.domain.workflow_schema import ensure_workflow_schema


def install_workflow_registry_and_pin_items(conn) -> None:
    """Converge built-ins and pin fixture items from their workflow marker."""
    ensure_workflow_schema(conn)
    converge_builtin_workflows(conn)
    for workflow_id in ("issue", "epic"):
        resolved_id, version_id = resolve_current_workflow_pin(
            conn,
            workflow_id,
        )
        conn.execute(
            "UPDATE items SET workflow_id = %s, workflow_version_id = %s "
            "WHERE type = %s",
            (resolved_id, version_id, workflow_id),
        )
    conn.commit()


__all__ = ["install_workflow_registry_and_pin_items"]
