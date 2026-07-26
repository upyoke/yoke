"""Behavioral capabilities interpreted from immutable workflow policies."""

from __future__ import annotations

from dataclasses import dataclass

from yoke_core.domain.workflow_gate_catalog import GATE_PLAN_SIMULATION
from yoke_core.domain.workflow_runtime import WorkflowRuntime

LANE_IMPLEMENTATION = "implementation"
LANE_WORKER = "worker"
LANE_INTEGRATION = "integration"


@dataclass(frozen=True)
class WorktreeLanePolicy:
    """Allowed and required lane roles for one immutable workflow version."""

    allowed_roles: frozenset[str]
    required_roles: frozenset[str]

    def allows(self, lane_role: str) -> bool:
        return lane_role in self.allowed_roles


_WORKTREE_LANE_POLICIES = {
    "single_implementation_lane": WorktreeLanePolicy(
        allowed_roles=frozenset({LANE_IMPLEMENTATION}),
        required_roles=frozenset({LANE_IMPLEMENTATION}),
    ),
    "worker_and_integration_lanes": WorktreeLanePolicy(
        allowed_roles=frozenset({LANE_WORKER, LANE_INTEGRATION}),
        required_roles=frozenset({LANE_WORKER, LANE_INTEGRATION}),
    ),
    "worker_lanes_optional_integration": WorktreeLanePolicy(
        allowed_roles=frozenset({LANE_WORKER, LANE_INTEGRATION}),
        required_roles=frozenset({LANE_WORKER}),
    ),
}


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


def worktree_lane_policy(runtime: WorkflowRuntime) -> WorktreeLanePolicy:
    """Interpret the definition's worktree policy as lane-role constraints."""
    policy_id = str(runtime.policies["worktrees"])
    return worktree_lane_policy_for_id(policy_id)


def worktree_lane_policy_for_id(policy_id: str) -> WorktreeLanePolicy:
    """Interpret one validated worktree-policy identifier."""
    try:
        return _WORKTREE_LANE_POLICIES[policy_id]
    except KeyError as exc:
        raise ValueError(f"unknown workflow worktree policy {policy_id!r}") from exc


__all__ = [
    "LANE_IMPLEMENTATION",
    "LANE_INTEGRATION",
    "LANE_WORKER",
    "WorktreeLanePolicy",
    "generates_task_graph",
    "release_note_category",
    "requires_plan_simulation",
    "worktree_lane_policy",
    "worktree_lane_policy_for_id",
]
