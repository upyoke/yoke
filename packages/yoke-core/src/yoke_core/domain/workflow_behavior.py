"""Behavioral capabilities interpreted from immutable workflow policies."""

from __future__ import annotations

from yoke_core.domain.workflow_gate_catalog import GATE_PLAN_SIMULATION
from yoke_core.domain.workflow_runtime import WorkflowRuntime


def generates_task_graph(runtime: WorkflowRuntime) -> bool:
    """Return whether the workflow owns persisted task children."""
    return runtime.policies["generated_children"] == "epic_tasks"


def requires_plan_simulation(runtime: WorkflowRuntime) -> bool:
    """Return whether any workflow stage declares the plan-simulation gate."""
    return any(
        GATE_PLAN_SIMULATION in runtime.gate_ids_for_stage(stage_id)
        for stage_id in runtime.stage_ids
    )


def release_note_category(runtime: WorkflowRuntime) -> str:
    """Map workflow delivery shape onto the existing release-note taxonomy."""
    if generates_task_graph(runtime):
        return "features"
    if (
        runtime.policies["delivery"] == "release_stage"
        and runtime.policies["worktrees"] == "single_implementation_lane"
    ):
        return "bug_fixes"
    return "improvements"


__all__ = [
    "generates_task_graph",
    "release_note_category",
    "requires_plan_simulation",
]
