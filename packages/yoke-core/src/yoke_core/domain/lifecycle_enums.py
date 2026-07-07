"""Canonical delivery-item lifecycle status enums.

This module owns the four canonical status enums for the software-delivery
workflow family plus the workflow-family scope metadata constants. Sibling
modules build on these enums for ordered collections, predicates, progression
helpers, and SQL/display rendering. The ``lifecycle`` front door re-exports
the full public surface for backwards-compatible imports.
"""

from __future__ import annotations

from enum import Enum

# ---------------------------------------------------------------------------
# Workflow family scope metadata
# ---------------------------------------------------------------------------

LIFECYCLE_FAMILY: str = "software-delivery"
LIFECYCLE_SCOPE: str = "workflow-family-local"

# ---------------------------------------------------------------------------
# Status enum -- canonical delivery item statuses
# ---------------------------------------------------------------------------


class ItemStatus(str, Enum):
    """Canonical delivery item statuses."""

    IDEA = "idea"
    PLANNED = "planned"
    RELEASE = "release"
    DONE = "done"
    CANCELLED = "cancelled"
    # BLOCKED is retained on the item-status enum only as legacy
    # drift detection. Post-cutover the canonical signal is items.blocked=1
    # (see yoke_core.domain.queries.is_blocked); HC-blocked-status-drift
    # surfaces any row that still holds this lifecycle position. The task
    # enum below keeps BLOCKED as a real status — epic-task semantics are
    # out of scope.
    BLOCKED = "blocked"
    STOPPED = "stopped"
    FAILED = "failed"

    # -- Issue-workflow-type statuses --
    REFINING_IDEA = "refining-idea"
    REFINED_IDEA = "refined-idea"
    IMPLEMENTING = "implementing"
    REVIEWING_IMPLEMENTATION = "reviewing-implementation"
    REVIEWED_IMPLEMENTATION = "reviewed-implementation"
    POLISHING_IMPLEMENTATION = "polishing-implementation"
    IMPLEMENTED = "implemented"

    # -- Epic-workflow-type statuses --
    PLANNING = "planning"
    PLAN_DRAFTED = "plan-drafted"
    REFINING_PLAN = "refining-plan"


class TaskStatus(str, Enum):
    """Canonical epic task statuses."""

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


class IssueStatus(str, Enum):
    """Canonical issue-workflow-type statuses."""

    IDEA = "idea"
    REFINING_IDEA = "refining-idea"
    REFINED_IDEA = "refined-idea"
    IMPLEMENTING = "implementing"
    REVIEWING_IMPLEMENTATION = "reviewing-implementation"
    REVIEWED_IMPLEMENTATION = "reviewed-implementation"
    POLISHING_IMPLEMENTATION = "polishing-implementation"
    IMPLEMENTED = "implemented"
    RELEASE = "release"
    DONE = "done"


class EpicStatus(str, Enum):
    """Canonical epic-workflow-type statuses."""

    IDEA = "idea"
    REFINING_IDEA = "refining-idea"
    REFINED_IDEA = "refined-idea"
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
