"""Shared public constants for item-owned worktree lane operations."""

from typing import Any, Mapping

ITEM_WORKTREE_LANE_IMPLEMENTATION = "implementation"
ITEM_WORKTREE_LANE_WORKER = "worker"
ITEM_WORKTREE_LANE_INTEGRATION = "integration"
ADDITIONAL_ITEM_WORKTREE_LANE_ROLES = (
    ITEM_WORKTREE_LANE_WORKER,
    ITEM_WORKTREE_LANE_INTEGRATION,
)
EVIDENCE_ONLY_RECOVERY_REASON = "evidence-only-recovery"

# The worktrees-policy value for a workflow that provisions no git lane at
# all. It lives here rather than beside the other policy vocabulary because
# client packages must read it without importing the engine.
WORKFLOW_WORKTREES_NONE = "none"


def runs_without_git_lane(workflow_projection: Mapping[str, Any]) -> bool:
    """Whether an item-detail workflow projection provisions no git lane.

    Callers hold the read model rather than a workflow runtime, and an
    item's posture may override a policy, so the effective values win over
    the pinned ones wherever the projection carries both.
    """
    policies = (
        workflow_projection.get("effective_policies")
        or workflow_projection.get("policies")
        or {}
    )
    return str(policies.get("worktrees") or "") == WORKFLOW_WORKTREES_NONE


__all__ = [
    "ADDITIONAL_ITEM_WORKTREE_LANE_ROLES",
    "EVIDENCE_ONLY_RECOVERY_REASON",
    "ITEM_WORKTREE_LANE_IMPLEMENTATION",
    "ITEM_WORKTREE_LANE_INTEGRATION",
    "ITEM_WORKTREE_LANE_WORKER",
    "WORKFLOW_WORKTREES_NONE",
    "runs_without_git_lane",
]
