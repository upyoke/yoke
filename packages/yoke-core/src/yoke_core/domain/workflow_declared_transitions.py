"""Declared-edge readings over an item's pinned workflow definition.

A workflow version declares its stage graph as explicit ``transitions``
edges. Stage membership answers "does this stage exist"; it does not answer
"may an item move there from where it stands". Only the second question
keeps an item from arriving at a later stage without passing through the
stages between, and a stage that is never reached never runs its own gates —
so a close-out straight from implementation carries no review verdict, and
nothing downstream can tell that apart from a reviewed one.

These readings compose over :class:`~yoke_core.domain.workflow_runtime.
WorkflowRuntime` rather than living on it, because they are policy questions
asked at two boundaries — the status write and the standalone merge — while
the runtime itself stays a plain interpretation of the stored definition.
"""

from __future__ import annotations

from typing import Optional

from yoke_core.domain.workflow_gate_catalog import activation_operation_gate_ids
from yoke_core.domain.workflow_runtime import WorkflowRuntime


def declared_transitions(workflow: WorkflowRuntime) -> frozenset[tuple[str, str]]:
    """Every ``(from, to)`` stage edge the pinned definition declares."""
    return frozenset(
        (str(edge["from_stage_id"]), str(edge["to_stage_id"]))
        for edge in workflow.definition["transitions"]
    )


def declares_transition(
    workflow: WorkflowRuntime,
    from_stage_id: str,
    to_stage_id: str,
) -> bool:
    """Whether the definition declares this exact edge."""
    return (from_stage_id, to_stage_id) in declared_transitions(workflow)


def declared_next_stage_ids(
    workflow: WorkflowRuntime,
    from_stage_id: str,
) -> tuple[str, ...]:
    """The stages this one declares an outgoing edge to, in stage order."""
    targets = {
        after
        for before, after in declared_transitions(workflow)
        if before == from_stage_id
    }
    return tuple(stage_id for stage_id in workflow.stage_ids if stage_id in targets)


def undeclared_forward_transition(
    workflow: WorkflowRuntime,
    *,
    from_stage_id: str,
    to_stage_id: str,
) -> str:
    """Refusal text for a forward move the definition does not declare.

    Empty when the move is allowed. Only forward moves between declared
    stages are judged: a move backwards is rework, a move to or from one of
    the universal exceptional stages is blocking or reopening, and a
    declared jump is the definition's own shortcut. None of those skips a
    stage's gates, so none of them is refused here.
    """
    if not workflow.is_forward_transition(from_stage_id, to_stage_id):
        return ""
    if declares_transition(workflow, from_stage_id, to_stage_id):
        return ""
    declared = declared_next_stage_ids(workflow, from_stage_id)
    return (
        f"{workflow.workflow_id}@{workflow.version} declares no transition "
        f"{from_stage_id!r} -> {to_stage_id!r}. Declared next stages from "
        f"{from_stage_id!r}: {', '.join(declared) or 'none'}. Advance one "
        "declared stage at a time so each stage runs its own gates. To "
        "reconcile a status that is recorded wrong rather than advance the "
        "work, an operator uses `yoke lifecycle repair-status`."
    )


def implementation_review_stage_id(workflow: WorkflowRuntime) -> Optional[str]:
    """The declared stage where review of the implementation begins.

    The implementation stage is the one whose gates activate the lane — the
    work claim, the path claims, the execution document. Review begins at
    the stage its declared forward edge leads to. ``None`` when the
    definition has no lane-activating stage, or when that stage leads
    straight to a terminal stage, which is the shape of a workflow that
    delivers without a review of its own.
    """
    activation_gate_ids = activation_operation_gate_ids()
    for stage_id in workflow.stage_ids:
        if not workflow.gate_ids_for_stage(stage_id) & activation_gate_ids:
            continue
        for candidate in declared_next_stage_ids(workflow, stage_id):
            if candidate in workflow.terminal_stage_ids:
                return None
            return candidate
        return None
    return None


def unreached_review_stage(workflow: WorkflowRuntime, stage_id: str) -> str:
    """The declared review stage this stage has not reached, else empty."""
    review_stage_id = implementation_review_stage_id(workflow)
    if review_stage_id is None:
        return ""
    if workflow.has_reached_stage(stage_id, review_stage_id):
        return ""
    return review_stage_id


__all__ = [
    "declared_next_stage_ids",
    "declared_transitions",
    "declares_transition",
    "implementation_review_stage_id",
    "undeclared_forward_transition",
    "unreached_review_stage",
]
