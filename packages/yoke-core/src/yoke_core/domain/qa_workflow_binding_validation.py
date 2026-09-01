"""Validate item QA bindings against the pinned workflow definition."""

from __future__ import annotations

from typing import Any, Mapping

from yoke_core.domain.workflow_definition_builders import (
    WORKFLOW_QA_OPTIONAL_ITEM_ATTACHMENT,
)
from yoke_core.domain.workflow_effective_policies import (
    EffectiveWorkflowPolicies,
    load_item_effective_workflow_policies,
)
from yoke_core.domain.workflow_gate_catalog import GATE_QA_VERIFICATION
from yoke_core.domain.workflow_runtime import (
    WorkflowRuntime,
    load_item_workflow_runtime,
)


ITEM_POSTURE_VERIFICATION_TRANSITION = "reviewing-implementation"


class QaWorkflowBindingError(ValueError):
    """An item QA binding has no valid gate in its pinned workflow."""


def transition_for_gate(
    workflow: WorkflowRuntime,
    gate_id: str,
) -> str:
    """Return the first stage that directly carries ``gate_id``."""
    for stage_id in workflow.stage_ids:
        if any(
            str(gate["id"]) == gate_id for gate in workflow.gates_for_stage(stage_id)
        ):
            return stage_id
    raise QaWorkflowBindingError(
        f"{workflow.workflow_id}@{workflow.version} has no {gate_id} gate"
    )


def item_transition_for_gate(
    conn: Any,
    *,
    item_id: int,
    gate_id: str,
) -> str:
    """Resolve a gate-bearing transition from an item's immutable pin."""
    return transition_for_gate(
        load_item_workflow_runtime(conn, int(item_id)),
        gate_id,
    )


def qa_enforcement_signature(
    workflow: WorkflowRuntime,
    transition_id: str,
) -> tuple[tuple[str, str | None], ...]:
    """Return every ordered QA gate reachable from a materialization stage."""
    position = workflow.stage_index(transition_id)
    if position is None:
        return ()
    return tuple(
        (stage_id, gate.get("mode"))
        for stage_id in workflow.stage_ids[position:]
        for gate in workflow.gates_for_stage(stage_id)
        if str(gate["id"]) == GATE_QA_VERIFICATION
    )


def _selected_verification_matches(
    effective: EffectiveWorkflowPolicies,
    *,
    transition_id: str,
    plan_id: Any,
    method_id: Any,
) -> bool:
    """Whether an optional item QA binding has a posture-owned runtime gate."""
    if (
        effective.values.get("qa") != WORKFLOW_QA_OPTIONAL_ITEM_ATTACHMENT
        or transition_id != ITEM_POSTURE_VERIFICATION_TRANSITION
    ):
        return False
    verification = effective.posture.get("verification")
    if not isinstance(verification, Mapping):
        return False
    kind = str(verification.get("kind") or "")
    if kind == "plan" and plan_id is not None:
        try:
            return int(verification.get("plan_id")) == int(plan_id)
        except (TypeError, ValueError):
            return False
    if kind == "ad_hoc" and method_id is not None:
        return str(verification.get("method_id") or "") == str(method_id)
    return False


def validate_item_qa_transition(
    conn: Any,
    *,
    item_id: int,
    transition_id: Any,
    plan_id: Any = None,
    method_id: Any = None,
) -> tuple[str, WorkflowRuntime]:
    """Require a definition- or selected-posture-enforced QA binding."""
    transition = str(transition_id or "").strip()
    if not transition:
        raise QaWorkflowBindingError(
            "workflow_transition_id is required for item/epic-attached QA"
        )
    effective = load_item_effective_workflow_policies(conn, int(item_id))
    workflow = effective.runtime
    if transition not in workflow.stage_ids:
        raise QaWorkflowBindingError(
            f"workflow transition {transition!r} is not in "
            f"{workflow.workflow_id}@{workflow.version}"
        )
    if qa_enforcement_signature(workflow, transition):
        return transition, workflow
    if _selected_verification_matches(
        effective,
        transition_id=transition,
        plan_id=plan_id,
        method_id=method_id,
    ):
        return transition, workflow
    message = (
        f"workflow transition {transition!r} has no reachable qa_verification gate"
    )
    if effective.values.get("qa") == WORKFLOW_QA_OPTIONAL_ITEM_ATTACHMENT:
        message += (
            "; optional item QA accepts only the plan or method selected "
            "in workflow_posture.verification. Select one on this item "
            "first: yoke workflows item-posture amend <PREFIX-N> "
            '--verification-plan <ID_OR_SLUG> --reason "<why>" '
            "(--help for the decision tree), then retry"
        )
    raise QaWorkflowBindingError(message)


__all__ = [
    "QaWorkflowBindingError",
    "ITEM_POSTURE_VERIFICATION_TRANSITION",
    "item_transition_for_gate",
    "qa_enforcement_signature",
    "transition_for_gate",
    "validate_item_qa_transition",
]
