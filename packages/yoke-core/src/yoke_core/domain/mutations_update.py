"""Item update mutation semantics."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from yoke_core.domain.workflow_definition_builders import (
    WORKFLOW_DELIVERY_CONTINUOUS_SLICE_THEN_RELEASE,
)

from .mutation_fields import (
    DONE_CLEANUP_FIELDS,
    SUPPORTED_UPDATE_FIELDS,
    GateContext,
    ItemState,
    MutationEvent,
    MutationEventKind,
    MutationResult,
    validate_blocked,
    validate_blocked_reason,
    validate_frozen,
    validate_priority,
    validate_title,
)
from yoke_core.domain.project_identity_item_ref import item_ref_for_id

#: Delivery policies whose done transition must go through the usher
#: done-transition ceremony rather than a raw status mutation — every policy
#: that waits on a release-stage gate before the terminal stage, including a
#: still-implementing Blitz's final closeout.
from yoke_core.domain.deployment_qa_source_obligation import POST_DEPLOY_RECOVERY
from yoke_core.domain.qa_gate_definitions import status_settles_blocking_qa

_RELEASE_CEREMONY_DELIVERY_POLICIES = frozenset(
    {"release_stage", WORKFLOW_DELIVERY_CONTINUOUS_SLICE_THEN_RELEASE}
)


def _ceremony_recovery(workflow: Any, item: Any) -> str:
    """Name the command that actually performs this item's done ceremony.

    Naming one skill for every workflow sent owners to a command their own
    definition does not bind — a Dash item has no usher leg, so the printed
    recovery could not be run at all. The pinned definition already says
    which skill owns the item's current stage, so ask it.
    """
    try:
        skill_id = workflow.skill_for_stage(str(item.status))
    except Exception:  # noqa: BLE001 - a refusal must not raise a second error
        skill_id = None
    if skill_id:
        return f"Close it out through '/yoke {skill_id} {item.ref}'."
    return (
        f"Close {item.ref} out through the close-out command its pinned "
        f"workflow binds; do not set 'done' directly."
    )


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
        err = validate_title(value, project=item.project, limit=gate.title_max_length)
        if err:
            return MutationResult(
                success=False,
                error=err,
                error_code="VALIDATION_ERROR",
                item_id=item.id,
            )

    elif field_name == "status":
        workflow = item.workflow
        if workflow is None:
            return MutationResult(
                success=False,
                error=(
                    f"{item_ref_for_id(item.id)} has no loaded workflow-version pin; "
                    "status validation cannot proceed."
                ),
                error_code="WORKFLOW_PIN_REQUIRED",
                item_id=item.id,
            )
        if not workflow.accepts_stage(value):
            valid = ", ".join(workflow.stage_ids)
            return MutationResult(
                success=False,
                error=(
                    f"'{value}' is not a valid stage for "
                    f"{workflow.workflow_id}@{workflow.version}. "
                    f"Defined stages: {valid} (plus universal exceptional "
                    "stages blocked, stopped, failed, cancelled)."
                ),
                error_code="VALIDATION_ERROR",
                item_id=item.id,
            )

        # --- Status transition gates ---

        # Epic task existence gate: block implementing for taskless epics
        # Updated from legacy ready/active to epic-family implementing
        if (
            value == "implementing"
            and workflow.policies["generated_children"] == "epic_tasks"
        ):
            if gate.epic_task_count is not None:
                if gate.epic_task_count == 0:
                    return MutationResult(
                        success=False,
                        error=(
                            f"Cannot set epic {item.ref} to '{value}' "
                            f"-- no epic_tasks found. Run '/yoke plan {item.ref}' first."
                        ),
                        error_code="GATE_EPIC_TASKS",
                        item_id=item.id,
                    )

        # Done-ceremony nonce gate: mutation layer trusts caller assertion
        if value == "done" and workflow.policies["delivery"] in _RELEASE_CEREMONY_DELIVERY_POLICIES:
            if not gate.force and not gate.done_nonce_verified:
                return MutationResult(
                    success=False,
                    error=(
                        f"Cannot set {item.ref} to 'done' -- missing done-transition "
                        f"ceremony nonce. "
                        f"{_ceremony_recovery(workflow, item)}"
                    ),
                    error_code="GATE_DONE_NONCE",
                    item_id=item.id,
                )

        # Epic merge gate: block epics from done without merged_at
        if value == "done" and workflow.policies["generated_children"] == "epic_tasks":
            if not gate.has_merged_at and not gate.force:
                return MutationResult(
                    success=False,
                    error=(
                        f"Cannot set epic {item.ref} to 'done' -- merged_at is not set. "
                        f"Epics must be merged before they can reach done status."
                    ),
                    error_code="GATE_EPIC_MERGE",
                    item_id=item.id,
                )

        # Settling-terminal QA gate: ``done`` must settle blocking obligations
        # this item carries. ``cancelled`` and ``stopped`` are named
        # non-settling terminals — they abandon without auto-waiving.
        if (
            status_settles_blocking_qa(value)
            and gate.unsatisfied_all_blocking > 0
            and not gate.qa_bypass
            and not gate.force
        ):
            recovery = (
                f" {POST_DEPLOY_RECOVERY}"
                if gate.unsatisfied_includes_post_deploy
                else ""
            )
            return MutationResult(
                success=False,
                error=(
                    gate.done_qa_refusal
                    or (
                        f"Cannot transition {item.ref} to '{value}' -- "
                        f"{gate.unsatisfied_all_blocking} blocking QA "
                        f"requirement(s) unsatisfied.{recovery}"
                    )
                ),
                error_code="GATE_QA_DONE",
                item_id=item.id,
            )

        # --- Status-change side effects ---

        # Done cleanup: clear item posture flags. Lane release is a
        # universal-registry side effect owned by the write adapter.
        if value == "done":
            for k, v in DONE_CLEANUP_FIELDS.items():
                field_writes[k] = v
            events.append(
                MutationEvent(
                    kind=MutationEventKind.DONE_CLEANUP,
                    detail=dict(DONE_CLEANUP_FIELDS),
                )
            )

        events.append(
            MutationEvent(
                kind=MutationEventKind.STATUS_TRANSITIONED,
                detail={
                    "from_status": item.status,
                    "to_status": value,
                    "is_forward": workflow.is_forward_transition(
                        item.status,
                        value,
                    ),
                },
            )
        )

    elif field_name == "priority":
        err = validate_priority(value)
        if err:
            return MutationResult(
                success=False,
                error=err,
                error_code="VALIDATION_ERROR",
                item_id=item.id,
            )

    elif field_name == "frozen":
        err = validate_frozen(value)
        if err:
            return MutationResult(
                success=False,
                error=err,
                error_code="VALIDATION_ERROR",
                item_id=item.id,
            )

    elif field_name == "blocked":
        err = validate_blocked(value)
        if err:
            return MutationResult(
                success=False,
                error=err,
                error_code="VALIDATION_ERROR",
                item_id=item.id,
            )

    elif field_name == "blocked_reason":
        err = validate_blocked_reason(value)
        if err:
            return MutationResult(
                success=False,
                error=err,
                error_code="VALIDATION_ERROR",
                item_id=item.id,
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
                            f"'{gate.flow_project}', but item {item.ref} "
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
        events.append(
            MutationEvent(
                kind=MutationEventKind.FIELD_UPDATED,
                detail={"field": field_name, "value": value},
            )
        )

    return MutationResult(
        success=True,
        field_writes=field_writes,
        events=tuple(events),
        item_id=item.id,
    )
