"""Merge state for delivery diagnostics and dated dependency landing facts."""

from __future__ import annotations

from typing import Any, Optional

from yoke_contracts.timestamps import InvalidInstant, parse_instant
from yoke_core.domain.dependency_types import GateResult
from yoke_core.domain.workflow_runtime import WorkflowRuntime


def evaluate_recorded_merge(merged_at: Any, created_at: Any) -> GateResult:
    """Only a recorded landing strictly after this edge can clear its wait."""
    try:
        landed = parse_instant(merged_at)
        created = parse_instant(created_at)
    except InvalidInstant:
        return GateResult(
            False,
            "merge_landing_unverified: landing or dependency creation time is missing "
            "or invalid; record the blocker's next landing through yoke merge item "
            "and inspect the edge with yoke items dependency list.",
        )
    if landed <= created:
        return GateResult(
            False,
            "merge_landing_predates_dependency: the recorded landing is not after "
            "this edge was created; wait for the blocker's next recorded landing.",
        )
    return GateResult(
        True, "Blocking item's recorded landing is after dependency creation."
    )


def evaluate_merge_state(
    blocking_status: str,
    blocking_worktree: Optional[str],
    blocking_merged: Optional[bool],
    workflow: WorkflowRuntime,
) -> GateResult:
    if blocking_merged is True:
        return GateResult(True, "Blocking item's merge is confirmed.")
    if blocking_merged is False:
        branch = f" ({blocking_worktree})" if blocking_worktree else ""
        return GateResult(
            False, f"Blocking item's branch{branch} is not yet merged to main."
        )
    if workflow.stage_implies_merge(blocking_status):
        return GateResult(
            True,
            f"Blocking item status is '{blocking_status}' (merge inferred).",
        )
    return GateResult(
        False,
        f"Blocking item status is '{blocking_status}'; branch merge not confirmed.",
    )
