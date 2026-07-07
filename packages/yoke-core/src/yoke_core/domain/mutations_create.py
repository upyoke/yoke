"""Item create mutation semantics."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional

from .lifecycle import is_valid_epic_status, is_valid_issue_status, is_valid_item_status
from .mutation_fields import (CreateResult, MutationEvent, MutationEventKind, validate_priority, validate_title, validate_type)

def prepare_create(
    *,
    title: str,
    item_type: str,
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
        item_type: 'epic' or 'issue'.
        priority: 'high', 'medium', or 'low'.
        project: Project ID. Defaults to adapter-resolved default.
        deployment_flow: Optional deployment flow ID.
        flow_project: Project the deployment flow belongs to (for
            cross-project validation).
        status: Optional initial status override.  Defaults to 'idea'.
            Validated against the type-aware lifecycle registry.

    Returns:
        CreateResult with success=True and field_writes on valid input,
        or success=False with error details.
    """
    # Validate title
    err = validate_title(title)
    if err:
        return CreateResult(success=False, error=err, error_code="VALIDATION_ERROR")

    # Validate type
    err = validate_type(item_type)
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

    # Type-aware create-time status validation.
    # When a status override is provided, validate it against the type-aware
    # lifecycle registry — the same validation used by prepare_update.
    effective_status = status or "idea"
    if status is not None and status != "idea":
        if item_type == "issue":
            if not is_valid_issue_status(status):
                return CreateResult(
                    success=False,
                    error=(
                        f"'{status}' is not a valid issue status. "
                        f"Issue items use the issue-workflow-type lifecycle: "
                        f"idea, refining-idea, refined-idea, implementing, "
                        f"reviewing-implementation, reviewed-implementation, "
                        f"polishing-implementation, "
                        f"implemented, release, done "
                        f"(plus blocked, stopped, failed, cancelled)."
                    ),
                    error_code="VALIDATION_ERROR",
                )
        elif item_type == "epic":
            if not is_valid_epic_status(status):
                return CreateResult(
                    success=False,
                    error=(
                        f"'{status}' is not a valid epic status. "
                        f"Epic items use the epic-workflow-type lifecycle: "
                        f"idea, refining-idea, refined-idea, planning, "
                        f"plan-drafted, refining-plan, planned, implementing, "
                        f"reviewing-implementation, reviewed-implementation, "
                        f"polishing-implementation, "
                        f"implemented, release, done "
                        f"(plus blocked, stopped, failed, cancelled)."
                    ),
                    error_code="VALIDATION_ERROR",
                )
        else:
            if not is_valid_item_status(status):
                return CreateResult(
                    success=False,
                    error=f"'{status}' is not a valid item status.",
                    error_code="VALIDATION_ERROR",
                )

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    defaults = {
        "status": effective_status,
        "flow": "accelerated",
        "rework_count": 0,
        "frozen": False,
        "blocked": False,
        "blocked_reason": None,
        "created_at": now,
        "updated_at": now,
    }

    field_writes = {
        "title": title,
        "type": item_type,
        "priority": priority,
        "status": effective_status,
        "project": project,
        "deployment_flow": deployment_flow,
        "flow": "accelerated",
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
            detail={"title": title, "type": item_type, "project": project},
        ),
    ]

    return CreateResult(
        success=True,
        field_writes=field_writes,
        defaults=defaults,
        events=tuple(events),
    )
