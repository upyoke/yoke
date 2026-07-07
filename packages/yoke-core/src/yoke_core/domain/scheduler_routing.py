"""Type-aware scheduler next-step routing."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

from .frontier import AdapterCategory
from .scheduler_types import NextStep, RoutingOverride

ROUTING_OVERRIDE_PATH_CLAIM_BLOCKED = "path_claim_activation_blocked"

# Epic-workflow-type adapter overrides.
# For shared tokens like ``idea`` where epic and issue routing diverge,
# this map provides the epic-specific adapter category.  Entries here
# override ``_STATUS_ADAPTER_MAP`` in ``frontier.py`` when the item is
# an epic.  The adapter is then converted to a NextStep via
# ``_ADAPTER_TO_STEP``.
_EPIC_ADAPTER_MAP: Dict[str, AdapterCategory] = {
    "idea": AdapterCategory.REFINE,
    "refining-idea": AdapterCategory.REFINE,
    "refined-idea": AdapterCategory.SHEPHERD,
    "planning": AdapterCategory.SHEPHERD,
    "plan-drafted": AdapterCategory.REFINE,
    "refining-plan": AdapterCategory.REFINE,
    "planned": AdapterCategory.CONDUCT,
    "implementing": AdapterCategory.CONDUCT,
    "reviewing-implementation": AdapterCategory.CONDUCT,
    "reviewed-implementation": AdapterCategory.POLISH,
    "polishing-implementation": AdapterCategory.POLISH,
    "implemented": AdapterCategory.USHER,
    "release": AdapterCategory.USHER,
}


@dataclass(frozen=True)
class _StepResult:
    """Internal result from _compute_next_step."""
    next_step: NextStep
    routing_override: Optional[RoutingOverride] = None


def _compute_next_step(
    item_type: str,
    status: str,
    adapter: AdapterCategory,
    *,
    conn: Optional[Any] = None,
    item_id: Optional[int] = None,
) -> _StepResult:
    """Map (item_type, status, adapter) to a scheduler-level next-step action.

    All routing flows through the adapter-to-step mapping -- no special-case
    early returns.

    Issue-workflow-type routing:
    - issue idea, refining-idea -> refine
    - issue refined-idea, implementing, reviewing-implementation -> advance
    - issue reviewed-implementation, polishing-implementation -> polish
    - issue implemented, release -> usher

    Epic-workflow-type routing:
    - epic idea, refining-idea -> refine
    - epic refined-idea, planning -> shepherd
    - epic plan-drafted, refining-plan -> refine
    - epic planned, implementing, reviewing-implementation -> conduct
    - epic reviewed-implementation, polishing-implementation -> polish
    - epic implemented, release -> usher
    """
    _ADAPTER_TO_STEP: Dict[AdapterCategory, NextStep] = {
        AdapterCategory.REFINE: NextStep.REFINE,
        AdapterCategory.SHEPHERD: NextStep.SHEPHERD,
        AdapterCategory.CONDUCT: NextStep.CONDUCT,
        AdapterCategory.POLISH: NextStep.POLISH,
        AdapterCategory.USHER: NextStep.USHER,
        AdapterCategory.WAIT: NextStep.WAIT,
        AdapterCategory.SKIP: NextStep.WAIT,
    }

    # Epic-workflow-type: use _EPIC_ADAPTER_MAP for explicit epic routing.
    if item_type == "epic" and status in _EPIC_ADAPTER_MAP:
        epic_adapter = _EPIC_ADAPTER_MAP[status]
        step = _ADAPTER_TO_STEP.get(epic_adapter, NextStep.WAIT)
        return _StepResult(step)

    # Default: derive next_step from the frontier adapter category.
    step = _ADAPTER_TO_STEP.get(adapter, NextStep.WAIT)

    # Issue-workflow-type CONDUCT -> ADVANCE: issues use /yoke advance for
    # main-session implementation, not /yoke conduct.
    if item_type == "issue" and step == NextStep.CONDUCT:
        step = NextStep.ADVANCE

    # Defense-in-depth: (issue, refined-idea, advance) dry-run probe.
    # INCOMPATIBLE → rewrite to refine so /yoke do routes through
    # readiness-repair instead of crashing in activation.
    if (
        conn is not None
        and item_id is not None
        and item_type == "issue"
        and status == "refined-idea"
        and step == NextStep.ADVANCE
    ):
        from .scheduler_path_claim_feasibility import (
            FeasibilityOutcome,
            probe_advance_feasibility,
        )
        verdict = probe_advance_feasibility(conn, item_id=item_id)
        if verdict.outcome is FeasibilityOutcome.BLOCKED_CROSS_ITEM_OVERLAP:
            override = RoutingOverride(
                reason=ROUTING_OVERRIDE_PATH_CLAIM_BLOCKED,
                original_step=NextStep.ADVANCE.value,
                conflicting_item_ids=list(verdict.conflicting_item_ids),
                conflicting_claim_ids=list(verdict.conflicting_claim_ids),
                shared_paths=list(verdict.shared_paths),
            )
            return _StepResult(NextStep.REFINE, routing_override=override)

    return _StepResult(step)
