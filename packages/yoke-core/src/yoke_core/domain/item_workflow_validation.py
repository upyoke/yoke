"""Validation of item stages against immutable workflow-version pins."""

from __future__ import annotations

from typing import Any

from yoke_core.domain.workflow_registry import WorkflowRegistryError
from yoke_core.domain.workflow_runtime import workflow_runtime_from_row


def invalid_item_workflow_stages(
    conn: Any,
) -> list[tuple[int, str, str]]:
    """Return items whose pin is incomplete, invalid, or rejects the stage."""
    rows = conn.execute(
        "SELECT i.id, i.status, i.workflow_id, i.workflow_version_id, "
        "v.version, v.definition_json, v.definition_digest "
        "FROM items i "
        "LEFT JOIN workflow_versions v ON v.id = i.workflow_version_id "
        "ORDER BY i.id"
    ).fetchall()
    invalid = []
    for raw in rows:
        row = dict(raw)
        item_id = int(row["id"])
        stage_id = str(row["status"])
        try:
            workflow = workflow_runtime_from_row(row)
            if workflow.workflow_id != str(row["workflow_id"]):
                raise WorkflowRegistryError("workflow id does not match pin")
            if not workflow.accepts_stage(stage_id):
                raise WorkflowRegistryError("stage is absent from definition")
        except (KeyError, TypeError, ValueError, WorkflowRegistryError) as exc:
            invalid.append((item_id, stage_id, str(exc)))
    return invalid


__all__ = ["invalid_item_workflow_stages"]
