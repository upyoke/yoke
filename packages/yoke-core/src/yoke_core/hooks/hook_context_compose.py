"""Collect advisory bodies from hook decisions for ordered, capped composition."""

from __future__ import annotations

from collections.abc import Iterable

from yoke_contracts.hook_context_compose import (
    FLEET_REPORT_CONTEXT_FIELD,
    FLEET_WATCHER_ALERT_CONTEXT_FIELD,
    classify_hook_context,
    compose_hook_context,
)
from yoke_core.hooks.types import HookDecision, Outcome


def composed_additional_context(
    decisions: Iterable[HookDecision],
    *,
    harness_id: str,
) -> str:
    """Delivery first, alerts, hints next, fleet report last, under the harness cap."""
    parts: dict[str, list[str]] = {
        "delivery": [],
        "alert": [],
        "hint": [],
        "report": [],
    }
    for decision in decisions:
        if decision.outcome is Outcome.DENY or decision.block:
            continue
        for field, kind in (
            (FLEET_WATCHER_ALERT_CONTEXT_FIELD, "alert"),
            (FLEET_REPORT_CONTEXT_FIELD, "report"),
        ):
            extra = decision.audit_fields.get(field)
            if isinstance(extra, str) and extra.strip():
                parts[kind].append(extra)
        value = decision.audit_fields.get("additionalContext")
        if isinstance(value, str) and value.strip():
            parts[classify_hook_context(value)].append(value)
    return compose_hook_context(
        parts["delivery"],
        parts["hint"],
        parts["report"],
        harness_id=harness_id,
        alerts=parts["alert"],
    )


__all__ = ["composed_additional_context"]
