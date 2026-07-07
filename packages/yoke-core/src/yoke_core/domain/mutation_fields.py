"""Mutation field definitions for the Yoke control plane.

Constants, result types, validation helpers, and state/gate dataclasses
extracted from mutations.py.  These are the field-level contracts consumed
by prepare_create, prepare_update, and prepare_approval in mutations.py.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, FrozenSet, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TITLE_MAX_LENGTH: int = 100
VALID_TYPES: FrozenSet[str] = frozenset({"epic", "issue"})
VALID_PRIORITIES: FrozenSet[str] = frozenset({"high", "medium", "low"})

# Fields supported by the update surface.
SUPPORTED_UPDATE_FIELDS: FrozenSet[str] = frozenset({
    "status", "frozen", "blocked", "blocked_reason",
    "priority", "project", "deployment_flow", "deployed_to", "title",
    "worktree",
})

# Statuses that trigger rework detection when work re-enters implementation.
REWORK_SOURCE_STATUSES: FrozenSet[str] = frozenset({
    "done",
    "implemented",
    "reviewed-implementation",
    "polishing-implementation",
})

# Fields cleared on done-transition cleanup.
DONE_CLEANUP_FIELDS: Dict[str, Any] = {
    "frozen": False,
    "blocked": False,
    "blocked_reason": None,
    "worktree": None,
}


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


class MutationEventKind(str, Enum):
    """Kinds of mutation events produced during a mutation."""
    CREATED = "created"
    FIELD_UPDATED = "field_updated"
    STATUS_TRANSITIONED = "status_transitioned"
    REWORK_INCREMENTED = "rework_incremented"
    DONE_CLEANUP = "done_cleanup"
    APPROVAL_APPLIED = "approval_applied"
    RUN_STAGE_ADVANCED = "run_stage_advanced"
    MEMBER_STAGE_SYNCED = "member_stage_synced"


@dataclass(frozen=True)
class MutationEvent:
    """A single mutation event produced during a mutation operation.

    Downstream adapters (API, shell) consume these to drive side effects
    like GitHub sync, board rebuilds, telemetry, etc.
    """
    kind: MutationEventKind
    detail: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class MutationResult:
    """Result of a mutation operation.

    Attributes:
        success: True if the mutation was valid and should be applied.
        error: Human-readable error message if the mutation was rejected.
        error_code: Machine-readable error code for API responses.
        events: Sequence of mutation events describing what changed.
        field_writes: Dict of field->value pairs to write to the DB.
            Adapters apply these writes in a single transaction.
        item_id: The item ID affected (set after create assigns an ID).
    """
    success: bool
    error: Optional[str] = None
    error_code: Optional[str] = None
    events: Tuple[MutationEvent, ...] = ()
    field_writes: Dict[str, Any] = field(default_factory=dict)
    item_id: Optional[int] = None


@dataclass(frozen=True)
class CreateResult(MutationResult):
    """Result of a create mutation, extending MutationResult with
    create-specific fields.

    Attributes:
        defaults: Dict of field->value defaults applied to the new item.
    """
    defaults: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ApprovalResult(MutationResult):
    """Result of an approval-apply mutation.

    Attributes:
        next_stage: The stage the run should advance to.
        run_id: The deployment run being advanced.
        member_item_ids: Item IDs of all run members to sync stage to.
        approved_at: ISO timestamp of approval.
    """
    next_stage: Optional[str] = None
    run_id: Optional[str] = None
    member_item_ids: Tuple[int, ...] = ()
    approved_at: Optional[str] = None


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


def validate_title(title: str) -> Optional[str]:
    """Validate title. Returns error message or None."""
    if not title or not title.strip():
        return "Field 'title' is required"
    if len(title) > TITLE_MAX_LENGTH:
        return (
            f"Title exceeds {TITLE_MAX_LENGTH} characters ({len(title)}). "
            f"Shorten it or move details to the body."
        )
    return None


def validate_type(item_type: str) -> Optional[str]:
    """Validate item type. Returns error message or None."""
    if item_type not in VALID_TYPES:
        return f"Invalid type '{item_type}'. Must be one of: {', '.join(sorted(VALID_TYPES))}"
    return None


def validate_priority(priority: str) -> Optional[str]:
    """Validate priority. Returns error message or None."""
    if priority not in VALID_PRIORITIES:
        return f"Invalid priority '{priority}'. Must be one of: {', '.join(sorted(VALID_PRIORITIES))}"
    return None


def validate_frozen(value: Any) -> Optional[str]:
    """Validate frozen field value. Returns error message or None."""
    if isinstance(value, bool):
        return None
    if isinstance(value, str) and value.lower() in ("true", "false"):
        return None
    return f"frozen must be true or false, got '{value}'"


def validate_blocked(value: Any) -> Optional[str]:
    """Validate blocked field value. Returns error message or None.

    Same shape as :func:`validate_frozen` — both are 0/1 boolean flags on
    items, exposed to operators as ``true``/``false`` strings or Python
    booleans through the update surface.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, str) and value.lower() in ("true", "false"):
        return None
    return f"blocked must be true or false, got '{value}'"


def validate_blocked_reason(value: Any) -> Optional[str]:
    """Validate blocked_reason. Allows None / empty / string."""
    if value is None:
        return None
    if isinstance(value, str):
        return None
    return f"blocked_reason must be a string or null, got {type(value).__name__}"


# ---------------------------------------------------------------------------
# Item state representation (read from DB by the adapter)
# ---------------------------------------------------------------------------


@dataclass
class ItemState:
    """Current state of an item, read from the DB by the adapter before
    calling a mutation function.

    Only the fields needed for mutation validation/semantics are included.
    """
    id: int
    title: str
    item_type: str
    status: str
    priority: str
    rework_count: int = 0
    frozen: bool = False
    blocked: bool = False
    blocked_reason: Optional[str] = None
    project: Optional[str] = None
    deployment_flow: Optional[str] = None
    deploy_stage: Optional[str] = None
    deployed_to: Optional[str] = None
    worktree: Optional[str] = None
    merged_at: Optional[str] = None


# ---------------------------------------------------------------------------
# Gate context (preloaded by the adapter to avoid DB calls in domain logic)
# ---------------------------------------------------------------------------


@dataclass
class GateContext:
    """Pre-loaded gate data that the adapter provides so the domain layer
    can make gate decisions without DB access.

    Attributes:
        epic_task_count: Number of epic_tasks rows for this item's epic.
            None if not applicable (non-epic items).
        qa_requirement_count: Total qa_requirements rows for this item.
        unsatisfied_verification_blocking: Count of blocking verification-phase
            requirements without a passing run or waiver.
        unsatisfied_all_blocking: Count of all blocking requirements
            (any phase) without a passing run or waiver.
        has_merged_at: Whether the item has a non-null merged_at.
        valid_deploy_envs: List of valid deployment environments for the
            item's project. None if not loaded.
        flow_project: Project that the deployment flow belongs to (for
            cross-project validation). None if no flow specified.
        done_nonce_verified: True if the caller has verified the done-
            ceremony nonce. The mutation layer trusts this assertion.
        force: True if the caller is using an explicit internal override.
            Callers using this escape hatch must preserve invariants outside
            the mutation layer.
        qa_bypass: True if QA gates should be bypassed.
    """
    epic_task_count: Optional[int] = None
    qa_requirement_count: int = 0
    unsatisfied_verification_blocking: int = 0
    unsatisfied_all_blocking: int = 0
    has_merged_at: bool = False
    valid_deploy_envs: Optional[List[str]] = None
    flow_project: Optional[str] = None
    done_nonce_verified: bool = False
    force: bool = False
    qa_bypass: bool = False
