"""Collect advisory bodies from hook decisions for ordered, capped composition."""

from __future__ import annotations

from collections.abc import Iterable

from yoke_contracts.hook_context_compose import (
    FLEET_REPORT_CONTEXT_FIELD,
    classify_hook_context,
    compose_hook_context,
)
from yoke_core.hooks.types import HookDecision, Outcome


def composed_additional_context(
    decisions: Iterable[HookDecision],
    *,
    harness_id: str,
) -> str:
    """Delivery first, hints next, fleet report last, under the harness cap."""
    deliveries: list[str] = []
    hints: list[str] = []
    reports: list[str] = []
    for decision in decisions:
        if decision.outcome is Outcome.DENY or decision.block:
            continue
        extra = decision.audit_fields.get(FLEET_REPORT_CONTEXT_FIELD)
        if isinstance(extra, str) and extra.strip():
            reports.append(extra)
        value = decision.audit_fields.get("additionalContext")
        if isinstance(value, str) and value.strip():
            kind = classify_hook_context(value)
            if kind == "delivery":
                deliveries.append(value)
            elif kind == "report":
                reports.append(value)
            else:
                hints.append(value)
    return compose_hook_context(
        deliveries, hints, reports, harness_id=harness_id
    )


__all__ = ["composed_additional_context"]
