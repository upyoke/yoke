"""Status set membership and validation predicates for the delivery lifecycle.

Owns the terminal/exceptional status frozensets and the validation +
terminal-state predicate functions consumed throughout the codebase. Imports
the canonical enums from ``lifecycle_enums``; the ``lifecycle`` front door
re-exports each public name for backwards-compatible imports.
"""

from __future__ import annotations

from typing import FrozenSet

from yoke_core.domain.lifecycle_enums import (
    EpicStatus,
    IssueStatus,
    ItemStatus,
    TaskStatus,
)

# ---------------------------------------------------------------------------
# Status sets -- used for fast membership checks
# ---------------------------------------------------------------------------

TERMINAL_SUCCESS: FrozenSet[str] = frozenset({"done"})
TERMINAL_FAILURE: FrozenSet[str] = frozenset({"stopped", "failed"})
TERMINAL: FrozenSet[str] = TERMINAL_SUCCESS | TERMINAL_FAILURE
# "blocked" remains in EXCEPTIONAL only as drift-detection. Post-
# cutover the canonical block signal is items.blocked=1; doctor surfaces any
# row that still holds the lifecycle position. Epic-task BLOCKED (out of
# (out of cutover scope) keeps its real meaning here.
EXCEPTIONAL: FrozenSet[str] = frozenset({"blocked", "stopped", "failed", "cancelled"})

# Task-specific terminal success — epic tasks use all post-review
# statuses as terminal success, distinct from item-level `done`.
# The full post-review progression is: reviewed-implementation →
# polishing-implementation → implemented → release.  All four (plus done) qualify.
# TASK_TERMINAL_SUCCESS relocated to yoke_contracts.lifecycle_status.
from yoke_contracts.lifecycle_status import (  # noqa: E402,F401
    TASK_TERMINAL_SUCCESS,
)


# ---------------------------------------------------------------------------
# Validation functions
# ---------------------------------------------------------------------------


def is_valid_item_status(status: str) -> bool:
    """Return True if *status* is a canonical delivery item status."""
    try:
        ItemStatus(status)
        return True
    except ValueError:
        return False


def is_valid_task_status(status: str) -> bool:
    """Return True if *status* is a canonical epic task status."""
    try:
        TaskStatus(status)
        return True
    except ValueError:
        return False


def is_valid_issue_status(status: str) -> bool:
    """Return True if *status* is valid for issue items.

    Accepts issue-workflow-type progression statuses plus exceptional states.
    """
    try:
        IssueStatus(status)
        return True
    except ValueError:
        return status in EXCEPTIONAL


def is_valid_epic_status(status: str) -> bool:
    """Return True if *status* is valid for epic items.

    Accepts epic-workflow-type progression statuses plus exceptional states.
    """
    try:
        EpicStatus(status)
        return True
    except ValueError:
        return status in EXCEPTIONAL


# ---------------------------------------------------------------------------
# Terminal-state checks
# ---------------------------------------------------------------------------


def is_terminal(status: str) -> bool:
    """Return True if *status* is a terminal status (success or failure)."""
    return status in TERMINAL


def is_terminal_success(status: str) -> bool:
    """Return True if *status* is a terminal success status."""
    return status in TERMINAL_SUCCESS


def is_terminal_failure(status: str) -> bool:
    """Return True if *status* is a terminal failure status."""
    return status in TERMINAL_FAILURE


def is_exceptional(status: str) -> bool:
    """Return True if *status* is an exceptional (non-progression) status."""
    return status in EXCEPTIONAL


def is_task_terminal_success(status: str) -> bool:
    """Return True if *status* is a terminal success status for epic tasks.

    Epic tasks use ``done|reviewed-implementation`` as terminal
    success, distinct from item-level terminal success (``done``).
    """
    return status in TASK_TERMINAL_SUCCESS
