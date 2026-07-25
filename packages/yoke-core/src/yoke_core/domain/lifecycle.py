"""Compatibility front door for the epic-task lifecycle vocabulary."""

from yoke_core.domain.task_lifecycle import (
    ALL_TASK_STATUSES,
    TASK_TERMINAL_SUCCESS,
    TERMINAL_FAILURE,
    TaskStatus,
    display_label,
    is_task_terminal_success,
    is_valid_task_status,
    sql_task_terminal_success_list,
)

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
