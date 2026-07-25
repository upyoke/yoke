"""Workflow-pin support for item fixture inserts."""

from __future__ import annotations

from typing import Any, Optional

from yoke_core.domain.schema_common import _table_exists
from yoke_core.domain.workflow_registry import (
    WorkflowRegistryError,
    resolve_current_workflow_pin,
)


def current_workflow_pin_if_available(
    conn: Any,
    workflow_id: str,
) -> Optional[tuple[str, int]]:
    """Resolve a fixture pin when its narrow schema includes the registry."""
    if not (
        _table_exists(conn, "workflows")
        and _table_exists(conn, "workflow_versions")
    ):
        return None
    try:
        return resolve_current_workflow_pin(conn, workflow_id)
    except WorkflowRegistryError:
        return None


__all__ = ["current_workflow_pin_if_available"]
