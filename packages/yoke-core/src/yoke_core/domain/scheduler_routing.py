"""Scheduler routing from registered executor adapters."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

from .frontier import AdapterCategory
from .scheduler_types import NextStep, RoutingOverride

ROUTING_OVERRIDE_PATH_CLAIM_BLOCKED = "path_claim_activation_blocked"

_ADAPTER_TO_STEP: Dict[AdapterCategory, NextStep] = {
    AdapterCategory.ADVANCE: NextStep.ADVANCE,
    AdapterCategory.BLITZ: NextStep.BLITZ,
    AdapterCategory.CONDUCT: NextStep.CONDUCT,
    AdapterCategory.DASH: NextStep.DASH,
    AdapterCategory.POLISH: NextStep.POLISH,
    AdapterCategory.REFINE: NextStep.REFINE,
    AdapterCategory.SHEPHERD: NextStep.SHEPHERD,
    AdapterCategory.USHER: NextStep.USHER,
    AdapterCategory.WAIT: NextStep.WAIT,
    AdapterCategory.SKIP: NextStep.WAIT,
}


@dataclass(frozen=True)
class _StepResult:
    """Internal result from ``_compute_next_step``."""

    next_step: NextStep
    routing_override: Optional[RoutingOverride] = None


def _compute_next_step(
    workflow_id: str,
    status: str,
    adapter: AdapterCategory,
    *,
    conn: Optional[Any] = None,
    item_id: Optional[int] = None,
) -> _StepResult:
    """Convert a definition-selected executor into a scheduler action."""
    del workflow_id
    step = _ADAPTER_TO_STEP.get(adapter, NextStep.WAIT)

    if (
        conn is not None
        and item_id is not None
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
