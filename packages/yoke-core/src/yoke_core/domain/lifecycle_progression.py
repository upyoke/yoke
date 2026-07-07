"""Ordered status collections and forward-transition helpers.

Owns the canonical issue/epic progression tuples, the ordered status tuples
derived from each enum, the board column display order, and the
forward-transition / progression-index helpers used by gate code, the
scheduler, and the board renderer. The ``lifecycle`` front door re-exports
each public name for backwards-compatible imports.
"""

from __future__ import annotations

from typing import Tuple

from yoke_core.domain.lifecycle_enums import (
    EpicStatus,
    IssueStatus,
    ItemStatus,
    TaskStatus,
)

# ---------------------------------------------------------------------------
# Ordered collections -- parallel to the shell space-separated lists
# ---------------------------------------------------------------------------

# Complete list of valid item statuses (matches STATUS_ALL ordering).
ALL_ITEM_STATUSES: Tuple[str, ...] = tuple(s.value for s in ItemStatus)

# Complete list of valid epic task statuses (matches STATUS_TASK_ALL ordering).
ALL_TASK_STATUSES: Tuple[str, ...] = tuple(s.value for s in TaskStatus)

# Complete list of valid issue-workflow-type statuses (matches STATUS_ISSUE_ALL ordering).
ALL_ISSUE_STATUSES: Tuple[str, ...] = tuple(s.value for s in IssueStatus)

# Complete list of valid epic-workflow-type statuses (matches STATUS_EPIC_ALL ordering).
ALL_EPIC_STATUSES: Tuple[str, ...] = tuple(s.value for s in EpicStatus)

# Canonical ordered progression for epic items.
# This is the normal forward path for epic parents.  Not every epic visits
# every status but when visited, ordering is respected.  Exceptional states
# (blocked, stopped, failed, cancelled) are NOT part of the progression.
#
# item-level "blocked" is a routing/display flag
# (items.blocked) and is not a forward lifecycle position. The string
# "blocked" appears below in board-bucket and exceptional-state listings
# only as legacy drift detection — yoke_core.engines.doctor_hc_blocked_flag
# surfaces any item row that still carries it as its `status`.
EPIC_PROGRESSION: Tuple[str, ...] = (
    "idea",
    "refining-idea",
    "refined-idea",
    "planning",
    "plan-drafted",
    "refining-plan",
    "planned",
    "implementing",
    "reviewing-implementation",
    "reviewed-implementation",
    "polishing-implementation",
    "implemented",
    "release",
    "done",
)

# Canonical ordered progression for issue items.
# Exceptional states (blocked, stopped, failed, cancelled) are NOT part of the
# progression -- they are reachable from multiple points.
ISSUE_PROGRESSION: Tuple[str, ...] = (
    "idea",
    "refining-idea",
    "refined-idea",
    "implementing",
    "reviewing-implementation",
    "reviewed-implementation",
    "polishing-implementation",
    "implemented",
    "release",
    "done",
)

# Statuses that appear before ``implementing`` in either progression — the
# purely bookkeeping rungs with no gates. Used by the session-cwd binding
# checks and the planning-phase path-claim parser to distinguish a
# pre-implementation item from one whose worktree is live execution authority.
PRE_IMPLEMENTATION_STATUSES: frozenset[str] = frozenset(
    EPIC_PROGRESSION[: EPIC_PROGRESSION.index("implementing")]
) | frozenset(
    ISSUE_PROGRESSION[: ISSUE_PROGRESSION.index("implementing")]
)

# Board display column order differs from delivery progression for operator
# readability.
BOARD_COLUMN_ORDER: Tuple[str, ...] = (
    "idea",
    "planning",
    "refined",
    "implementing",
    "blocked",
    "reviewing",
    "implemented",
    "release",
    "done",
)

# ---------------------------------------------------------------------------
# Progression helpers
# ---------------------------------------------------------------------------

_EPIC_PROGRESSION_INDEX = {s: i for i, s in enumerate(EPIC_PROGRESSION)}
_ISSUE_PROGRESSION_INDEX = {s: i for i, s in enumerate(ISSUE_PROGRESSION)}
_PROGRESSION_INDEX = _EPIC_PROGRESSION_INDEX


def epic_progression_index(status: str) -> int | None:
    """Return the zero-based index of *status* in the epic progression.

    Returns ``None`` if the status is not part of the epic progression
    (i.e., it is an exceptional status or an issue-only status).
    """
    return _EPIC_PROGRESSION_INDEX.get(status)


def is_epic_forward_transition(from_status: str, to_status: str) -> bool:
    """Return True if moving from *from_status* to *to_status* is a forward
    step in the canonical epic progression.

    Returns False if either status is not in the epic progression or if
    *to_status* does not come after *from_status*.
    """
    from_idx = _EPIC_PROGRESSION_INDEX.get(from_status)
    to_idx = _EPIC_PROGRESSION_INDEX.get(to_status)
    if from_idx is None or to_idx is None:
        return False
    return to_idx > from_idx


def progression_index(status: str, *, item_type: str | None = None) -> int | None:
    """Return the zero-based index of *status* in a delivery progression.

    When *item_type* is ``"issue"``, uses the issue progression.  When
    *item_type* is ``"epic"`` or ``None`` (default), uses the epic progression.
    This maintains backward compatibility -- existing callers that do not pass
    *item_type* get the epic (formerly shared/delivery) progression.

    Returns ``None`` if the status is not part of the selected progression
    (i.e., it is an exceptional status like blocked/stopped/failed/cancelled).
    """
    if item_type == "issue":
        return _ISSUE_PROGRESSION_INDEX.get(status)
    return _EPIC_PROGRESSION_INDEX.get(status)


def is_forward_transition(
    from_status: str, to_status: str, *, item_type: str | None = None
) -> bool:
    """Return True if moving from *from_status* to *to_status* is a forward
    step in a canonical delivery progression.

    When *item_type* is ``"issue"``, uses the issue progression.  When
    *item_type* is ``"epic"`` or ``None`` (default), uses the epic progression.

    Returns False if either status is not in the selected progression or if
    *to_status* does not come after *from_status*.
    """
    if item_type == "issue":
        idx = _ISSUE_PROGRESSION_INDEX
    else:
        idx = _EPIC_PROGRESSION_INDEX
    from_idx = idx.get(from_status)
    to_idx = idx.get(to_status)
    if from_idx is None or to_idx is None:
        return False
    return to_idx > from_idx
