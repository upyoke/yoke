"""Lifecycle vocabulary for epic tasks."""

from __future__ import annotations

from enum import Enum

from yoke_core.domain.workflow_runtime import load_item_workflow_runtime
from yoke_contracts.lifecycle_status import (
    ENGINE_TERMINAL_STAGE_IDS,
    ENGINE_WAIT_STAGE_IDS,
)


class TaskStatus(str, Enum):
    """Canonical epic-task statuses."""

    PLANNING = "planning"
    PLAN_DRAFTED = "plan-drafted"
    REFINING_PLAN = "refining-plan"
    PLANNED = "planned"
    IMPLEMENTING = "implementing"
    REVIEWING_IMPLEMENTATION = "reviewing-implementation"
    REVIEWED_IMPLEMENTATION = "reviewed-implementation"
    POLISHING_IMPLEMENTATION = "polishing-implementation"
    IMPLEMENTED = "implemented"
    RELEASE = "release"
    DONE = "done"
    FAILED = "failed"
    BLOCKED = "blocked"
    STOPPED = "stopped"


ALL_TASK_STATUSES = tuple(status.value for status in TaskStatus)
TERMINAL_FAILURE = (ENGINE_TERMINAL_STAGE_IDS - {"cancelled"}) | ENGINE_WAIT_STAGE_IDS


def is_valid_task_status(status: str) -> bool:
    """Whether a string is a registered epic-task status."""
    try:
        TaskStatus(status)
        return True
    except ValueError:
        return False


def task_success_statuses(conn, epic_id: int) -> frozenset[str]:
    """Read task success from the parent's immutable workflow pin."""
    return load_item_workflow_runtime(conn, int(epic_id)).successful_task_stage_ids


def is_task_terminal_success(conn, epic_id: int, status: str) -> bool:
    """Whether a task reached its definition-owned handoff."""
    return status in task_success_statuses(conn, epic_id)


def display_label(status: str) -> str:
    """Render a stored hyphenated task status for humans."""
    return status.replace("-", " ")


__all__ = [
    "ALL_TASK_STATUSES",
    "task_success_statuses",
    "TERMINAL_FAILURE",
    "TaskStatus",
    "display_label",
    "is_task_terminal_success",
    "is_valid_task_status",
]
