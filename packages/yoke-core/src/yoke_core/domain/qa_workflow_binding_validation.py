"""Validate item QA bindings against the pinned workflow definition."""

from __future__ import annotations

from typing import Any

from yoke_core.domain.workflow_gate_catalog import GATE_QA_VERIFICATION
from yoke_core.domain.workflow_runtime import (
    WorkflowRuntime,
    load_item_workflow_runtime,
)


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


def validate_item_qa_transition(
    conn: Any,
    *,
    item_id: int,
    transition_id: Any,
) -> tuple[str, WorkflowRuntime]:
    """Require a nonempty, QA-gated stage in the item's pinned workflow."""
    transition = str(transition_id or "").strip()
    if not transition:
        raise QaWorkflowBindingError(
            "workflow_transition_id is required for item/epic-attached QA"
        )
    workflow = load_item_workflow_runtime(conn, int(item_id))
    if transition not in workflow.stage_ids:
        raise QaWorkflowBindingError(
            f"workflow transition {transition!r} is not in "
            f"{workflow.workflow_id}@{workflow.version}"
        )
    if not qa_enforcement_signature(workflow, transition):
        raise QaWorkflowBindingError(
            f"workflow transition {transition!r} has no reachable qa_verification gate"
        )
    return transition, workflow


__all__ = [
    "QaWorkflowBindingError",
    "item_transition_for_gate",
    "qa_enforcement_signature",
    "transition_for_gate",
    "validate_item_qa_transition",
]
