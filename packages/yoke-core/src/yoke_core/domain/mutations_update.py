"""Item update mutation semantics."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from .lifecycle import is_forward_transition, is_valid_epic_status, is_valid_issue_status, is_valid_item_status
from .mutation_fields import (DONE_CLEANUP_FIELDS, REWORK_SOURCE_STATUSES, SUPPORTED_UPDATE_FIELDS, GateContext, ItemState, MutationEvent, MutationEventKind, MutationResult, validate_blocked, validate_blocked_reason, validate_frozen, validate_priority, validate_title)

def prepare_update(
    *,
    item: ItemState,
    field_name: str,
    value: Any,
    gate: Optional[GateContext] = None,
) -> MutationResult:
    """Validate and prepare a single-field item update.

    This function validates the update and returns a MutationResult with
    the field writes needed.  The adapter applies writes in a single
    transaction.

    Args:
        item: Current item state (read from DB by adapter).
        field_name: The field to update.
        value: The new value.
        gate: Pre-loaded gate context for transition checks.

    Returns:
        MutationResult with success=True and field_writes on valid input,
        or success=False with error details.
    """
    if field_name not in SUPPORTED_UPDATE_FIELDS:
        return MutationResult(
            success=False,
            error=f"Field '{field_name}' is not in the supported update surface.",
            error_code="UNSUPPORTED_FIELD",
            item_id=item.id,
        )

    gate = gate or GateContext()
    field_writes: Dict[str, Any] = {}
    events: List[MutationEvent] = []
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # --- Field-specific validation ---

    if field_name == "title":
        err = validate_title(value)
        if err:
            return MutationResult(
                success=False, error=err,
                error_code="VALIDATION_ERROR", item_id=item.id,
            )

    elif field_name == "status":
        # Type-aware status validation.
        # Issue items validate against the issue-workflow-type registry (rejects
        # legacy shared-only statuses like defined/designed/planned/ready/
        # active/review/validate/passed).  Epic items validate against the
        # epic-workflow-type registry (rejects legacy shared-only statuses like
        # defined/designed/ready/active/review/validate/passed).  All other
        # types validate against the full shared registry.
        if item.item_type == "issue":
            if not is_valid_issue_status(value):
                return MutationResult(
                    success=False,
                    error=(
                        f"'{value}' is not a valid issue status. "
                        f"Issue items use the issue-workflow-type lifecycle: "
                        f"idea, refining-idea, refined-idea, implementing, "
                        f"reviewing-implementation, reviewed-implementation, "
                        f"polishing-implementation, "
                        f"implemented, release, done "
                        f"(plus blocked, stopped, failed, cancelled)."
                    ),
                    error_code="VALIDATION_ERROR",
                    item_id=item.id,
                )
        elif item.item_type == "epic":
            if not is_valid_epic_status(value):
                return MutationResult(
                    success=False,
                    error=(
                        f"'{value}' is not a valid epic status. "
                        f"Epic items use the epic-workflow-type lifecycle: "
                        f"idea, refining-idea, refined-idea, planning, "
                        f"refining-plan, planned, implementing, "
                        f"reviewing-implementation, reviewed-implementation, "
                        f"polishing-implementation, "
                        f"implemented, release, done "
                        f"(plus blocked, stopped, failed, cancelled)."
                    ),
                    error_code="VALIDATION_ERROR",
                    item_id=item.id,
                )
        else:
            if not is_valid_item_status(value):
                return MutationResult(
                    success=False,
                    error=f"'{value}' is not a valid item status",
                    error_code="VALIDATION_ERROR",
                    item_id=item.id,
                )

        # --- Status transition gates ---

        # Epic task existence gate: block implementing for taskless epics
        # Updated from legacy ready/active to epic-family implementing
        if value in ("implementing",) and item.item_type == "epic":
            if gate.epic_task_count is not None:
                if gate.epic_task_count == 0:
                    return MutationResult(
                        success=False,
                        error=(
                            f"Cannot set epic YOK-{item.id} to '{value}' "
                            f"-- no epic_tasks found. Run '/yoke plan YOK-{item.id}' first."
                        ),
                        error_code="GATE_EPIC_TASKS",
                        item_id=item.id,
                    )

        # Done-ceremony nonce gate: mutation layer trusts caller assertion
        if value == "done":
            if not gate.force and not gate.done_nonce_verified:
                return MutationResult(
                    success=False,
                    error=(
                        f"Cannot set YOK-{item.id} to 'done' -- missing done-transition "
                        f"ceremony nonce. Use '/yoke usher YOK-{item.id}'."
                    ),
                    error_code="GATE_DONE_NONCE",
                    item_id=item.id,
                )

        # Epic merge gate: block epics from done without merged_at
        if value == "done" and item.item_type == "epic":
            if not gate.has_merged_at and not gate.force:
                return MutationResult(
                    success=False,
                    error=(
                        f"Cannot set epic YOK-{item.id} to 'done' -- merged_at is not set. "
                        f"Epics must be merged before they can reach done status."
                    ),
                    error_code="GATE_EPIC_MERGE",
                    item_id=item.id,
                )

        # QA gates
        if not gate.qa_bypass and not gate.force:
            # review entry gate: needs qa_requirements rows
            if value == "reviewing-implementation":
                if gate.qa_requirement_count == 0:
                    return MutationResult(
                        success=False,
                        error=(
                            f"Cannot transition YOK-{item.id} to 'reviewing-implementation' "
                            f"-- no qa_requirements found."
                        ),
                        error_code="GATE_QA_REVIEWING",
                        item_id=item.id,
                    )

            # implemented gate: all blocking verification-phase requirements satisfied
            if value == "implemented":
                if gate.unsatisfied_verification_blocking > 0:
                    return MutationResult(
                        success=False,
                        error=(
                            f"Cannot transition YOK-{item.id} to 'implemented' -- "
                            f"{gate.unsatisfied_verification_blocking} blocking verification "
                            f"requirement(s) unsatisfied."
                        ),
                        error_code="GATE_QA_IMPLEMENTED",
                        item_id=item.id,
                    )

            # release gate: usher must not pick up items whose verification
            # requirements were never actually satisfied.
            if value == "release":
                if gate.unsatisfied_verification_blocking > 0:
                    return MutationResult(
                        success=False,
                        error=(
                            f"Cannot transition YOK-{item.id} to 'release' -- "
                            f"{gate.unsatisfied_verification_blocking} blocking verification "
                            f"requirement(s) unsatisfied."
                        ),
                        error_code="GATE_QA_RELEASE",
                        item_id=item.id,
                    )

            # done gate: all blocking requirements (any phase) satisfied
            if value == "done":
                if gate.unsatisfied_all_blocking > 0:
                    return MutationResult(
                        success=False,
                        error=(
                            f"Cannot transition YOK-{item.id} to 'done' -- "
                            f"{gate.unsatisfied_all_blocking} blocking QA "
                            f"requirement(s) unsatisfied."
                        ),
                        error_code="GATE_QA_DONE",
                        item_id=item.id,
                    )

        # --- Status-change side effects ---

        # Rework detection: reopened work increments rework_count when it
        # re-enters active implementation.
        rework_target = value == "implementing"
        if rework_target and item.status in REWORK_SOURCE_STATUSES:
            new_rework = item.rework_count + 1
            field_writes["rework_count"] = new_rework
            events.append(MutationEvent(
                kind=MutationEventKind.REWORK_INCREMENTED,
                detail={
                    "from_status": item.status,
                    "to_status": value,
                    "rework_count": new_rework,
                },
            ))

        # Done cleanup: clear frozen, worktree
        if value == "done":
            for k, v in DONE_CLEANUP_FIELDS.items():
                field_writes[k] = v
            events.append(MutationEvent(
                kind=MutationEventKind.DONE_CLEANUP,
                detail=dict(DONE_CLEANUP_FIELDS),
            ))

        events.append(MutationEvent(
            kind=MutationEventKind.STATUS_TRANSITIONED,
            detail={
                "from_status": item.status,
                "to_status": value,
                "is_forward": is_forward_transition(item.status, value, item_type=item.item_type),
            },
        ))

    elif field_name == "priority":
        err = validate_priority(value)
        if err:
            return MutationResult(
                success=False, error=err,
                error_code="VALIDATION_ERROR", item_id=item.id,
            )

    elif field_name == "frozen":
        err = validate_frozen(value)
        if err:
            return MutationResult(
                success=False, error=err,
                error_code="VALIDATION_ERROR", item_id=item.id,
            )

    elif field_name == "blocked":
        err = validate_blocked(value)
        if err:
            return MutationResult(
                success=False, error=err,
                error_code="VALIDATION_ERROR", item_id=item.id,
            )

    elif field_name == "blocked_reason":
        err = validate_blocked_reason(value)
        if err:
            return MutationResult(
                success=False, error=err,
                error_code="VALIDATION_ERROR", item_id=item.id,
            )

    elif field_name == "deployment_flow":
        # Validate flow belongs to same project as the item
        if value is not None and value != "null" and value:
            if gate.flow_project and item.project:
                if gate.flow_project != item.project:
                    return MutationResult(
                        success=False,
                        error=(
                            f"Deployment flow '{value}' belongs to project "
                            f"'{gate.flow_project}', but item YOK-{item.id} "
                            f"project is '{item.project}'."
                        ),
                        error_code="VALIDATION_ERROR",
                        item_id=item.id,
                    )

    elif field_name == "deployed_to":
        # project-scoped deployment environment validation
        if value is not None and value != "null" and value:
            if gate.valid_deploy_envs is not None:
                if not gate.valid_deploy_envs:
                    return MutationResult(
                        success=False,
                        error=(
                            f"No deployment environments configured for project "
                            f"'{item.project}'."
                        ),
                        error_code="VALIDATION_ERROR",
                        item_id=item.id,
                    )
                if value not in gate.valid_deploy_envs:
                    return MutationResult(
                        success=False,
                        error=(
                            f"deployed_to '{value}' is not valid for project "
                            f"'{item.project}'. Valid environments: "
                            f"{','.join(gate.valid_deploy_envs)}"
                        ),
                        error_code="VALIDATION_ERROR",
                        item_id=item.id,
                    )

    # The primary field write
    field_writes[field_name] = value
    field_writes["updated_at"] = now

    if not events:
        events.append(MutationEvent(
            kind=MutationEventKind.FIELD_UPDATED,
            detail={"field": field_name, "value": value},
        ))

    return MutationResult(
        success=True,
        field_writes=field_writes,
        events=tuple(events),
        item_id=item.id,
    )
