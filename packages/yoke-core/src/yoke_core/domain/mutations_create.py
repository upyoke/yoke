"""Item create mutation semantics."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional

from .mutation_fields import (
    CreateResult,
    MutationEvent,
    MutationEventKind,
    validate_priority,
    validate_title,
)
from .workflow_runtime import WorkflowRuntime

def prepare_create(
    *,
    title: str,
    workflow: WorkflowRuntime,
    priority: str = "medium",
    project: Optional[str] = None,
    deployment_flow: Optional[str] = None,
    flow_project: Optional[str] = None,
    status: Optional[str] = None,
) -> CreateResult:
    """Validate and prepare an item creation.

    This function validates inputs and returns a CreateResult with the
    field writes needed to insert a new item.  The adapter is responsible
    for the actual DB insert and ID assignment.

    Args:
        title: Item title (max 100 chars).
        workflow: Immutable workflow version selected for the new item.
        priority: 'high', 'medium', or 'low'.
        project: Project ID. Defaults to adapter-resolved default.
        deployment_flow: Optional deployment flow ID.
        flow_project: Project the deployment flow belongs to (for
            cross-project validation).
        status: Optional initial status override.  Defaults to 'idea'.
            Validated against the selected workflow version.

    Returns:
        CreateResult with success=True and field_writes on valid input,
        or success=False with error details.
    """
    # Validate title
    err = validate_title(title)
    if err:
        return CreateResult(success=False, error=err, error_code="VALIDATION_ERROR")

    # Validate priority
    err = validate_priority(priority)
    if err:
        return CreateResult(success=False, error=err, error_code="VALIDATION_ERROR")

    # Validate deployment flow project match
    if deployment_flow and flow_project and project:
        if flow_project != project:
            return CreateResult(
                success=False,
                error=(
                    f"Deployment flow '{deployment_flow}' belongs to project "
                    f"'{flow_project}', but item project is '{project}'."
                ),
                error_code="VALIDATION_ERROR",
            )

    effective_status = status or workflow.stage_ids[0]
    if not workflow.accepts_stage(effective_status):
        return CreateResult(
            success=False,
            error=(
                f"'{effective_status}' is not a valid stage for workflow "
                f"{workflow.workflow_id}@{workflow.version}. Valid stages: "
                f"{', '.join(workflow.stage_ids)}."
            ),
            error_code="VALIDATION_ERROR",
        )

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    defaults = {
        "status": effective_status,
        "rework_count": 0,
        "frozen": False,
        "blocked": False,
        "blocked_reason": None,
        "created_at": now,
        "updated_at": now,
    }

    field_writes = {
        "title": title,
        "workflow_id": workflow.workflow_id,
        "workflow_version_id": workflow.workflow_version_id,
        "priority": priority,
        "status": effective_status,
        "project": project,
        "deployment_flow": deployment_flow,
        "rework_count": 0,
        "frozen": False,
        "blocked": False,
        "blocked_reason": None,
        "created_at": now,
        "updated_at": now,
    }

    events: List[MutationEvent] = [
        MutationEvent(
            kind=MutationEventKind.CREATED,
            detail={
                "title": title,
                "workflow_id": workflow.workflow_id,
                "workflow_version_id": workflow.workflow_version_id,
                "project": project,
            },
        ),
    ]

    return CreateResult(
        success=True,
        field_writes=field_writes,
        defaults=defaults,
        events=tuple(events),
    )
