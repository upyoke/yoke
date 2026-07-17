"""Shared scheduler dataclasses and enums."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

class NextStep(str, Enum):
    """Scheduler-level action for an item on the frontier.

    Values:
        REFINE: Issue needs refinement (idea/refining-idea).
        SHEPHERD: Pre-ready epic -- needs maturation via shepherd pipeline.
        CONDUCT: Epic implementation work (ready/active/review).
        ADVANCE: Issue implementation work (refined-idea/implementing/
            reviewing-implementation). Routes to /yoke advance
            for main-session issue implementation.
        POLISH: Item needs finishing review
            (reviewed-implementation/polishing-implementation).
        USHER: Passed/validate/release/implemented -- merge and deploy.
        WAIT: Blocked, exceptional, or no action available.
    """

    REFINE = "refine"
    SHEPHERD = "shepherd"
    CONDUCT = "conduct"
    ADVANCE = "advance"
    POLISH = "polish"
    USHER = "usher"
    WAIT = "wait"


# ---------------------------------------------------------------------------
# Claim state — per-item claim evaluation
# ---------------------------------------------------------------------------


class ClaimState(str, Enum):
    """Claim state for an item relative to a session.

    Values:
        UNCLAIMED: No active exclusive claim exists.
        CLAIMED_BY_SELF: The offering session holds the claim.
        CLAIMED_BY_OTHER_LIVE: Another live session holds the claim.
        CLAIMED_BY_STALE: A stale/ended session holds the claim.
    """

    UNCLAIMED = "unclaimed"
    CLAIMED_BY_SELF = "claimed_by_self"
    CLAIMED_BY_OTHER_LIVE = "claimed_by_other_live"
    CLAIMED_BY_STALE = "claimed_by_stale"


@dataclass(frozen=True)
class RoutingOverride:
    """Routing override applied by the scheduler when a deterministic
    next-step lookup is rewritten by a feasibility probe.

    ``reason`` is the canonical override identifier (e.g.
    ``path_claim_activation_blocked``). ``original_step`` is the
    NextStep value the routing table would have returned without the
    override; rendered as a bare string so telemetry consumers do not
    need to import the enum.
    """

    reason: str
    original_step: str
    conflicting_item_ids: List[str] = field(default_factory=list)
    conflicting_claim_ids: List[int] = field(default_factory=list)
    shared_paths: List[str] = field(default_factory=list)

    def to_context_dict(self) -> Dict[str, Any]:
        # Canonical payload consumed by FrontierStepSelected events and
        # the NextActionChosen scheduler_context block.
        return {
            "routing_override": self.reason,
            "routing_override_original_step": self.original_step,
            "routing_override_conflicting_item_ids": list(self.conflicting_item_ids),
            "routing_override_conflicting_claim_ids": list(self.conflicting_claim_ids),
            "routing_override_shared_paths": list(self.shared_paths),
        }


def is_assignable_claim_state(state: ClaimState) -> bool:
    """Return True when ``state`` makes a ranked step assignable to the
    offering session.

    The single source of truth for the assignability rule. Used by the
    scheduler's selected-step search and by every operator-facing
    projection that exposes a ``runnable_items`` / ``Runnable`` list:
    a ``CLAIMED_BY_OTHER_LIVE`` step stays on the raw ranked frontier
    for diagnostics but is not assignable to a different session.
    """
    return state in (
        ClaimState.UNCLAIMED,
        ClaimState.CLAIMED_BY_SELF,
        ClaimState.CLAIMED_BY_STALE,
    )


# ---------------------------------------------------------------------------
# SML state
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SMLState:
    """Strategic Markdown Layer state for scheduling decisions.

    Attributes:
        coherent: True when every project in scope carries all default
            strategy docs as live (non-archived) ``strategy_docs`` rows.
            This is the sole hard-truth SML precondition kept in the
            public contract. ``stale`` and ``basis`` were removed — the
            post-delivery drift-review model replaces ambient stale-bit
            decisioning.
    """

    coherent: bool = True


# ---------------------------------------------------------------------------
# Gate evaluation — per-dependency detail
# ---------------------------------------------------------------------------


@dataclass
class GateEvaluation:
    """A single dependency gate evaluation for a scheduled step.

    Attributes:
        blocking_item: The YOK-N ID of the blocker.
        relation: Always ``blocker`` in the canonical model.
        gate_point: When the dependency matters (e.g., ``activation``).
        satisfaction: What must be true for resolution (e.g., ``status:done``).
        satisfied: Whether the condition is currently met.
        reason: Human-readable explanation from the shared planning kernel.
        rationale: Persisted rationale from the dependency row, explaining
            why this edge exists.
    """

    blocking_item: str
    relation: str
    gate_point: str
    satisfaction: str
    satisfied: bool
    reason: str
    rationale: str = ""


# ---------------------------------------------------------------------------
# Scheduled step — enriched frontier item
# ---------------------------------------------------------------------------


@dataclass
class ScheduledStep:
    """A single item on the scheduler's output with full context.

    Attributes:
        item_id: Item identifier (``YOK-N``).
        item_type: ``epic`` or ``issue``.
        status: Current canonical status.
        title: Item title.
        priority: Priority level.
        project: Slug of the project the item belongs to (empty when the
            producing path predates project labelling).
        next_step: Scheduler-level action for this item.
        rank: Zero-based position in the deterministic ranking.
        claim_state: Claim evaluation relative to the offering session.
        gate_evaluations: Dependency gates that affect scheduling.
        explanation: Human-readable explanation of the scheduling decision.
        adapter: The raw adapter category from frontier computation.
        blocked_by: List of blocker item IDs.
        blocked_reasons: Human-readable blocking reasons.
        unblocks_count: How many items this item hard-blocks.
        downstream_depth: Length of the longest downstream activation-gate
            chain from this item.
        created_at: ISO 8601 creation timestamp.
    """

    item_id: str
    item_type: str
    status: str
    title: str
    priority: str
    next_step: NextStep
    project: str = ""
    rank: int = 0
    claim_state: ClaimState = ClaimState.UNCLAIMED
    gate_evaluations: List[GateEvaluation] = field(default_factory=list)
    explanation: str = ""
    adapter: str = ""
    blocked_by: List[str] = field(default_factory=list)
    blocked_reasons: List[str] = field(default_factory=list)
    unblocks_count: int = 0
    downstream_depth: int = 0
    created_at: str = ""
    routing_override: Optional[RoutingOverride] = None


# ---------------------------------------------------------------------------
# Scheduler result — the shared contract
# ---------------------------------------------------------------------------


@dataclass
class SchedulerResult:
    """Result of the shared frontier-step scheduler.

    Both ``/yoke do`` and ``/yoke charge`` consume this result.

    Attributes:
        project_scope: The list of project ids this result was computed
            across. The all-projects default is resolved upstream into the
            full registered set before reaching the scheduler.
        sml_state: Strategic Markdown Layer state.
        selected_step: The highest-ranked assignable step, or None.
        ranked_steps: All runnable steps sorted by rank.
        blocked_steps: Steps blocked by dependencies or exceptional status.
        exceptional_steps: Steps in failed status (visible for escalation).
        wip_cap: WIP cap used in computation.
        wip_active: Current WIP count.
        conduct_eligible: Conduct-eligible steps within WIP cap.
        frozen_steps: Frozen items (excluded from scheduling).
        lane_filtered_count: Number of ranked steps dropped by session-offer
            lane/harness compatibility filtering. Populated by
            ``_filter_schedule_for_offer`` after scheduling.
        lane_filtered_items: Structured details of the dropped steps, keyed
            by ``item_id`` with ``title``, ``status``, ``next_step``,
            ``required_path``, ``rank``, and ``claim_state``. Empty when
            nothing was filtered.
    """

    project_scope: List[int] = field(default_factory=list)
    sml_state: SMLState = field(default_factory=SMLState)
    selected_step: Optional[ScheduledStep] = None
    ranked_steps: List[ScheduledStep] = field(default_factory=list)
    blocked_steps: List[ScheduledStep] = field(default_factory=list)
    exceptional_steps: List[ScheduledStep] = field(default_factory=list)
    wip_cap: int = 5
    wip_active: int = 0
    conduct_eligible: List[ScheduledStep] = field(default_factory=list)
    frozen_steps: List[ScheduledStep] = field(default_factory=list)
    lane_filtered_count: int = 0
    lane_filtered_items: List[Dict[str, Any]] = field(default_factory=list)
