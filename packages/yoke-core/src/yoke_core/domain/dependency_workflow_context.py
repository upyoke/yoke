"""Workflow-version context helpers for dependency evaluation."""

from __future__ import annotations

from typing import Any, Optional

from yoke_core.domain.workflow_runtime import (
    WorkflowRuntime,
    workflow_runtime_from_row,
)


def workflow_from_joined_values(
    workflow_id: Any,
    workflow_version_id: Any,
    version: Any,
    definition_json: Any,
    definition_digest: Any,
) -> Optional[WorkflowRuntime]:
    """Interpret workflow columns joined onto a blocking item."""
    values = (
        workflow_id,
        workflow_version_id,
        version,
        definition_json,
        definition_digest,
    )
    if any(value is None for value in values):
        return None
    return workflow_runtime_from_row({
        "workflow_id": workflow_id,
        "workflow_version_id": workflow_version_id,
        "version": version,
        "definition_json": definition_json,
        "definition_digest": definition_digest,
    })


__all__ = ["workflow_from_joined_values"]
