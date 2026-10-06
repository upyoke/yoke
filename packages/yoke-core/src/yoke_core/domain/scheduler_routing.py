"""Scheduler routing from registered skill adapters."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

from yoke_contracts.skill_registry import STAGE_SKILL_IDS

from .frontier import AdapterCategory
from .scheduler_types import NextStep, RoutingOverride

ROUTING_OVERRIDE_PATH_CLAIM_BLOCKED = "path_claim_activation_blocked"

_ADAPTER_TO_STEP: Dict[AdapterCategory, NextStep] = {
    adapter: NextStep(adapter.value)
    if adapter.value in STAGE_SKILL_IDS
    else NextStep.WAIT
    for adapter in AdapterCategory
}


@dataclass(frozen=True)
class _StepResult:
    """Internal result from ``_compute_next_step``."""

    next_step: NextStep
    routing_override: Optional[RoutingOverride] = None


def _compute_next_step(
    adapter: AdapterCategory,
    *,
    probe_path_claim_activation: bool = False,
    conn: Optional[Any] = None,
    item_id: Optional[int] = None,
) -> _StepResult:
    """Convert a definition-selected skill into a scheduler action."""
    step = _ADAPTER_TO_STEP.get(adapter, NextStep.WAIT)

    if (
        conn is not None
        and item_id is not None
        and probe_path_claim_activation
        and step == NextStep.IMPLEMENT
    ):
        from .scheduler_path_claim_feasibility import (
            FeasibilityOutcome,
            probe_implement_feasibility,
        )

        verdict = probe_implement_feasibility(conn, item_id=item_id)
        if verdict.outcome is FeasibilityOutcome.BLOCKED_CROSS_ITEM_OVERLAP:
            override = RoutingOverride(
                reason=ROUTING_OVERRIDE_PATH_CLAIM_BLOCKED,
                original_step=NextStep.IMPLEMENT.value,
                conflicting_item_ids=list(verdict.conflicting_item_ids),
                conflicting_claim_ids=list(verdict.conflicting_claim_ids),
                shared_paths=list(verdict.shared_paths),
            )
            return _StepResult(
                NextStep.REFINE,
                routing_override=override,
            )
    return _StepResult(step)


__all__ = [
    "ROUTING_OVERRIDE_PATH_CLAIM_BLOCKED",
    "_StepResult",
    "_compute_next_step",
]
