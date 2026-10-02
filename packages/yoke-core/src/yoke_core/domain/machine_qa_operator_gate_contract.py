"""Closed declarative contract for Machine QA operator gates."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any


def normalize_operator_gate(
    action: Mapping[str, Any],
    normalized_action: dict[str, Any],
    *,
    strings: Callable[..., list[str]],
) -> None:
    """Validate and append the one registered operator gate in place."""
    step = str(normalized_action["step"])
    operator_gate = action.get("operator_gate")
    if operator_gate is not None:
        if operator_gate != "machine_browser_approval":
            raise ValueError("action operator_gate is not registered")
        if normalized_action["keys"] != ["Enter"]:
            raise ValueError(
                "machine_browser_approval must immediately send Enter"
            )
        if "wait_seconds" in normalized_action:
            raise ValueError(
                "operator actions must use a typed gate, not wait_seconds"
            )
        completion_text = strings(
            action.get("completion_text"),
            field="action completion_text",
        )
        gate_timeout = action.get("gate_timeout_seconds")
        if (
            isinstance(gate_timeout, bool)
            or not isinstance(gate_timeout, (int, float))
            or not 1 <= float(gate_timeout) <= 600
        ):
            raise ValueError(
                "action gate_timeout_seconds must be numeric from 1..600"
            )
        normalized_action.update(
            {
                "operator_gate": operator_gate,
                "completion_text": completion_text,
                "gate_timeout_seconds": float(gate_timeout),
            }
        )
    elif "operator" in step.casefold() and "wait_seconds" in normalized_action:
        raise ValueError(
            "operator actions must use a typed gate, not wait_seconds"
        )
    elif "completion_text" in action or "gate_timeout_seconds" in action:
        raise ValueError(
            "completion_text and gate_timeout_seconds require operator_gate"
        )


__all__ = ["normalize_operator_gate"]
