"""Resolve the next registered skill from a pinned workflow definition."""

from __future__ import annotations

from .frontier_types import AdapterCategory
from .workflow_runtime import (
    ENGINE_TERMINAL_STAGE_IDS,
    ENGINE_WAIT_STAGE_IDS,
    WorkflowRuntime,
)


def classify_next_action(
    workflow: WorkflowRuntime,
    stage_id: str,
) -> AdapterCategory:
    """Map an item's current stage to its definition-bound skill."""
    if (
        stage_id in workflow.terminal_stage_ids
        or stage_id in ENGINE_TERMINAL_STAGE_IDS
    ):
        return AdapterCategory.SKIP
    if stage_id in ENGINE_WAIT_STAGE_IDS:
        return AdapterCategory.WAIT
    if not workflow.accepts_stage(stage_id):
        raise ValueError(
            f"Unknown stage {stage_id!r} for "
            f"{workflow.workflow_id}@{workflow.version}"
        )
    skill_id = workflow.skill_for_stage(stage_id)
    if skill_id is None:
        return AdapterCategory.SKIP
    try:
        return AdapterCategory(skill_id)
    except ValueError as exc:
        raise ValueError(
            f"Workflow skill {skill_id!r} has no frontier adapter"
        ) from exc


__all__ = ["classify_next_action"]
