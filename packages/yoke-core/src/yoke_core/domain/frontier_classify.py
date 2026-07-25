"""Resolve the next registered executor from a pinned workflow definition."""

from __future__ import annotations

from .frontier_types import AdapterCategory
from .workflow_runtime import WorkflowRuntime

_SKIP_STAGES = frozenset({"cancelled", "done", "stopped"})
_WAIT_STAGES = frozenset({"blocked", "failed"})


def classify_next_action(
    workflow: WorkflowRuntime,
    stage_id: str,
) -> AdapterCategory:
    """Map an item's current stage to its definition-bound executor."""
    if stage_id in _SKIP_STAGES:
        return AdapterCategory.SKIP
    if stage_id in _WAIT_STAGES:
        return AdapterCategory.WAIT
    if not workflow.accepts_stage(stage_id):
        raise ValueError(
            f"Unknown stage {stage_id!r} for "
            f"{workflow.workflow_id}@{workflow.version}"
        )
    executor_id = workflow.executor_for_stage(stage_id)
    if executor_id is None:
        return AdapterCategory.SKIP
    try:
        return AdapterCategory(executor_id)
    except ValueError as exc:
        raise ValueError(
            f"Workflow executor {executor_id!r} has no frontier adapter"
        ) from exc


__all__ = ["classify_next_action"]
