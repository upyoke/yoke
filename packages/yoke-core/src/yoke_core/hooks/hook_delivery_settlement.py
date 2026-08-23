"""Aggregate model-delivery output and settle its durable receipts."""

from __future__ import annotations

from collections.abc import Iterable

from yoke_core.hooks import (
    session_broker_wake,
    session_launch_attestation,
    session_message_delivery,
)
from yoke_core.hooks.types import HookDecision, Outcome


def _provisional_stdout(decisions: Iterable[HookDecision]) -> str:
    parts: list[str] = []
    for decision in decisions:
        for field in (
            session_message_delivery.DELIVERY_AUDIT_FIELD,
            session_launch_attestation.LAUNCH_DELIVERY_AUDIT_FIELD,
            session_broker_wake.BROKER_AUDIT_FIELD,
        ):
            delivery = decision.audit_fields.get(field)
            if not isinstance(delivery, dict):
                continue
            if delivery.get("output_field") != "stdout":
                continue
            rendered = delivery.get("rendered_text")
            if isinstance(rendered, str) and rendered:
                parts.append(rendered)
    return "".join(parts)


def settle_model_deliveries(
    decisions: Iterable[HookDecision], rendered_text: str
) -> tuple[str, str]:
    """Append allowed lifecycle context, then settle every provisional delivery."""
    decision_list = list(decisions)
    denied = any(
        decision.outcome is Outcome.DENY or decision.block for decision in decision_list
    )
    final_text = rendered_text
    if not denied:
        final_text += _provisional_stdout(decision_list)
    session_message_delivery.settle_after_render(
        decision_list, rendered_text=final_text, denied=denied
    )
    session_launch_attestation.settle_after_render(
        decision_list, rendered_text=final_text, denied=denied
    )
    session_broker_wake.settle_after_render(
        decision_list, rendered_text=final_text, denied=denied
    )
    return final_text, "deny" if denied else "allow"


__all__ = ["settle_model_deliveries"]
