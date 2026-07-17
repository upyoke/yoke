"""Session-offer data contract and public event shapes."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

class ActionKind(str, Enum):
    """Canonical next-action directives the core may issue to a session.

    Values:
        RESUME: Continue work on an existing in-progress item.
        CHARGE: Pick up a new item and begin implementation.
        FEED: Refresh frontier facts, update stale frontier items, and materialize new work from the SML.
        STRATEGIZE: Guided SML review -- research, propose, and approve Strategic Markdown Layer updates.
        WAIT: No actionable work right now; wait and re-offer later.
        ESCALATE: A situation requires human attention or a different executor.
    """

    RESUME = "resume"
    CHARGE = "charge"
    FEED = "feed"
    STRATEGIZE = "strategize"
    WAIT = "wait"
    ESCALATE = "escalate"


# Alias for downstream consumers that prefer the NextAction-oriented naming.
NextActionKind = ActionKind


# ---------------------------------------------------------------------------
# Request envelope
# ---------------------------------------------------------------------------


class SessionOffer(BaseModel):
    """A harness session offering itself to Yoke for work assignment.

    Identity fields (``session_id``, ``executor``, ``execution_lane``) are
    stable for the session lifetime and sufficient for later claim/lease,
    heartbeat, and resume correlation.

    Attributes:
        session_id: Globally unique session identifier.  Stable for the
            session lifetime.  Used as the correlation key for heartbeat,
            claim/lease, and ledger events.
        executor: Harness identity (e.g., ``claude-code``, ``codex``,
            ``api``).  Multiple sessions may share an executor identity.
        provider: Model provider (e.g., ``anthropic``, ``openai``).
        model: Model identifier string (e.g., ``claude-opus-4-7``).
        capabilities: List of capability tags the session supports
            (e.g., ``["browser", "shell", "file_write", "github"]``).
        workspace: Absolute path or identifier for the working
            directory/repo the session operates in.
        execution_lane: Delivery-family lane identity (e.g., ``DARIUS``,
            ``ALTMAN``).  Used by the core for lane-aware issue routing.
            Legacy values (``primary``, ``review``) are accepted for
            backward compatibility.
        offered_at: ISO 8601 UTC timestamp of when the offer was created.
    """

    session_id: str = Field(
        ...,
        description="Globally unique session identifier, stable for session lifetime.",
    )
    executor: str = Field(
        ...,
        description="Harness identity (e.g., claude-code, codex, api).",
    )
    provider: str = Field(
        ...,
        description="Model provider (e.g., anthropic, openai).",
    )
    model: str = Field(
        ...,
        description="Model identifier string (e.g., claude-opus-4-7).",
    )
    capabilities: List[str] = Field(
        default_factory=list,
        description="Capability tags the session supports (e.g., browser, shell).",
    )
    workspace: str = Field(
        ...,
        description="Absolute path or identifier for the working directory/repo.",
    )
    execution_lane: str = Field(
        default="primary",
        description=(
            "Delivery-family lane identity (e.g., DARIUS, ALTMAN). "
            "Used by the core for lane-aware issue routing. "
            "Legacy values (primary, review) are accepted for backward compatibility."
        ),
    )
    offered_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        description="ISO 8601 UTC timestamp of when the offer was created.",
    )
    step: int = Field(
        default=1,
        ge=1,
        description="1-based loop iteration number for this session offer.",
    )
    supported_paths: List[str] = Field(
        default_factory=list,
        description=(
            "Canonical downstream path names this session can execute "
            "(e.g., refine, shepherd, conduct, polish, usher).  Empty list "
            "means all paths are supported (backward compatible)."
        ),
    )


# ---------------------------------------------------------------------------
# Response envelope
# ---------------------------------------------------------------------------


class NextAction(BaseModel):
    """Core directive returned to a session after evaluating its offer.

    The ``action`` field tells the adapter what kind of work to perform.
    The ``context`` dict carries action-specific payload (e.g., item
    reference for ``resume``/``charge``, wait duration for ``wait``).

    Attributes:
        action: The directive kind -- one of the six canonical values.
        reason: Human-readable explanation of why this action was chosen.
        correlation_id: Links back to the ``SessionOffer.session_id`` that
            triggered this directive.
        context: Optional dict for action-specific payload.  Keys depend
            on the action kind -- see contract documentation for details.
    """

    action: ActionKind = Field(
        ...,
        description="Directive kind: resume, charge, feed, strategize, wait, escalate.",
    )
    reason: str = Field(
        ...,
        description="Human-readable explanation of why this action was chosen.",
    )
    chainable: bool = Field(
        default=False,
        description="True when the loop may immediately re-offer after this action completes.",
    )
    correlation_id: str = Field(
        ...,
        description="Links back to the SessionOffer.session_id.",
    )
    context: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Action-specific payload (item ref, wait duration, etc.).",
    )

    @property
    def kind(self) -> ActionKind:
        """Alias for ``action`` — matches the NextAction naming convention."""
        return self.action


# ---------------------------------------------------------------------------
# Event shape constants
# ---------------------------------------------------------------------------

# These constants document the event shapes emitted by the session-offer loop.
# They are registered in the event_registry table and conform to
# the envelope structure in docs/event-contract.md.

SESSION_OFFERED_EVENT = {
    "event_name": "HarnessSessionOffered",
    "event_kind": "system",
    "event_type": "session_offer",
    "description": "A harness session offered itself to Yoke for work assignment.",
    "minimum_context_fields": [
        "session_id",
        "executor",
        "provider",
        "model",
        "execution_lane",
        "workspace",
        "capabilities",
        "supported_paths",
    ],
}

NEXT_ACTION_CHOSEN_EVENT = {
    "event_name": "NextActionChosen",
    "event_kind": "workflow",
    "event_type": "session_directive",
    "description": "The core chose a next-action directive for an offered session.",
    "minimum_context_fields": [
        "session_id",
        "action",
        "reason",
        "chainable",
        "correlation_id",
        "step",
    ],
    # Indexed fields populated by the emitter when the action targets a
    # specific work unit:
    #   --item-id:  resume -> context.item_id, charge -> context.selected_item
    #   --task-num: resume with epic task context -> context.task_num
    #
    # Action-specific context keys (merged from response context):
    #   resume:     item_id, epic_id, task_num, status
    #   charge:     selected_item, runnable_items, scheduler
    #   escalate:   blocked_items, exceptional_items, blocked_details
    #   feed:       blocked_count, trigger
    #   strategize: sml_coherent
    #   drift_review: classification, summary, checkpoint_start, reviewed_through
    #   wait:       (none)
}


# ---------------------------------------------------------------------------
# Decision engine inputs (pure dataclasses — no DB, no I/O)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ClaimedWork:
    """Describes work already claimed by the offering session.

    Populated by the API layer from the ``work_claims`` / ``harness_sessions``
    tables before calling ``decide_next_action``.

    Attributes:
        item_id: YOK-N item identifier.
        epic_id: Epic ID for epic-task claims.
        task_num: Task number within the epic.
        status: Current canonical status of the claimed work.
        item_type: ``issue`` or ``epic`` — needed for type-aware routing.
            Populated by the service layer.
        required_path: Canonical downstream path derived from scheduler
            routing truth.  ``None`` when the path could
            not be derived (backward compat).
    """

    item_id: Optional[str] = None
    epic_id: Optional[int] = None
    task_num: Optional[int] = None
    status: Optional[str] = None
    item_type: Optional[str] = None
    required_path: Optional[str] = None


@dataclass(frozen=True)
class FrontierState:
    """Snapshot of the materialized frontier presented to the decision engine.

    All fields are pre-computed by the caller (API/service layer) from the
    shared scheduler (``scheduler.py``).  The decision engine never touches
    the DB itself.

    Attributes:
        runnable_items: Item IDs (``YOK-N``) assignable to the offering
            session. Includes non-terminal, non-frozen, non-blocked
            ranked steps whose ``claim_state`` is ``unclaimed``,
            ``claimed_by_self``, or ``claimed_by_stale`` — ranked steps
            held by another live session (``claimed_by_other_live``)
            stay on the raw ranked frontier for diagnostics but are
            excluded from this list. The shared assignability rule lives
            in ``yoke_core.domain.scheduler_types.is_assignable_claim_state``.
        blocked_items: Item IDs that are explicitly ``blocked`` or currently
            blocked by hard-block dependencies / policy gates.
        blocked_details: Per-blocker structured details for inter-item gate
            blockages on blocked items. Each entry includes ``item_id``,
            ``gate_point``, ``satisfaction``, ``rationale``, and ``reason``
            (evaluation explanation). ``None`` when no inter-item gate
            evaluations are unsatisfied.
        intrinsic_blocked_reasons: Per-item intrinsic-reason details for
            blocked items whose blockage does not come from an inter-item
            dependency edge. Each entry has ``item_id``, ``status``, and
            ``reasons`` (list of verbatim strings authored upstream in
            ``frontier_compute`` — operator-set block, legacy
            ``status='blocked'``, idea-incomplete, and routed-ownership
            defense). Parallel channel to ``blocked_details``; a row can
            populate either channel, both, or neither.
            ``None`` when no blocked step carries intrinsic reasons.
        exceptional_items: Item IDs in ``failed`` status that require
            operator attention (contribute to escalate).
        sml_coherent: True when every project in scope carries all
            default strategy docs as live (non-archived)
            ``strategy_docs`` rows.  This is the sole hard-truth SML
            precondition.
        drift_review: Result of the project-scoped post-delivery drift
            review, or None if the trigger did not fire.  When present,
            it is a dict with ``classification`` (``neither``,
            ``frontier_only``, ``sml_only``, ``both``), ``summary``,
            ``checkpoint_start``, ``reviewed_through``, and
            ``delivered_items``.
        selected_item: The highest-ranked assignable item ID, or None.
        scheduler_context: Additional context from the scheduler for
            the ``charge`` action (item details, next-step, etc.).
    """

    runnable_items: List[str] = field(default_factory=list)
    blocked_items: List[str] = field(default_factory=list)
    exceptional_items: List[str] = field(default_factory=list)
    blocked_details: Optional[List[Dict[str, Any]]] = None
    intrinsic_blocked_reasons: Optional[List[Dict[str, Any]]] = None
    sml_coherent: bool = True
    drift_review: Optional[Dict[str, Any]] = None
    selected_item: Optional[str] = None
    scheduler_context: Optional[Dict[str, Any]] = None
    lane_filtered_count: int = 0
    lane_filtered_items: Optional[List[Dict[str, Any]]] = None
    last_completed_step: Optional[Dict[str, Any]] = None

_CHAINABLE_ACTIONS = frozenset({ActionKind.RESUME, ActionKind.CHARGE})
