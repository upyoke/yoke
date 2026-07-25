"""Lifecycle vocabulary for epic tasks."""

from __future__ import annotations

from enum import Enum

from yoke_contracts.lifecycle_status import TASK_TERMINAL_SUCCESS


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
TERMINAL_FAILURE = frozenset({"stopped", "failed"})


def is_valid_task_status(status: str) -> bool:
    """Whether a string is a registered epic-task status."""
    try:
        TaskStatus(status)
        return True
    except ValueError:
        return False


def is_task_terminal_success(status: str) -> bool:
    """Whether a task reached a successful handoff or terminal stage."""
    return status in TASK_TERMINAL_SUCCESS


def sql_task_terminal_success_list() -> str:
    """Return a SQL IN-clause fragment for successful task statuses."""
    return ",".join(f"'{status}'" for status in sorted(TASK_TERMINAL_SUCCESS))


def display_label(status: str) -> str:
    """Render a stored hyphenated task status for humans."""
    return status.replace("-", " ")


__all__ = [
    "ALL_TASK_STATUSES",
    "TASK_TERMINAL_SUCCESS",
    "TERMINAL_FAILURE",
    "TaskStatus",
    "display_label",
    "is_task_terminal_success",
    "is_valid_task_status",
    "sql_task_terminal_success_list",
]
