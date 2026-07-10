"""Pure routing-state interpretation for self-hosted Actions runners."""

from __future__ import annotations

from typing import Sequence

from yoke_core.domain import json_helper


def routing_matches(value: str | None, required: Sequence[str]) -> bool:
    """Return whether the repo variable semantically names the required labels."""
    if not value:
        return False
    try:
        parsed = json_helper.loads_text(value)
    except (TypeError, ValueError):
        return False
    if not isinstance(parsed, list):
        return False
    labels = [item.strip().casefold() for item in parsed if isinstance(item, str)]
    expected = [item.strip().casefold() for item in required]
    return (
        len(labels) == len(parsed) == len(expected)
        and all(labels)
        and set(labels) == set(expected)
    )


def classify_runner_route(
    *,
    matching_count: int,
    online_count: int,
    routing_armed: bool,
    autoscaled_ephemeral: bool,
) -> tuple[str, str]:
    """Classify online readiness separately from armed scale-to-zero routing."""
    if online_count > 0:
        if routing_armed:
            return "ready", "Matching online runner exists and routing is armed."
        return "set_variable", "Matching online runner exists; set the runner variable."
    if matching_count > 0:
        return "start_runner", "Matching runners exist, but none are online."
    if autoscaled_ephemeral:
        if routing_armed:
            return (
                "routing_armed_idle",
                "Runner routing is armed and autoscaling is configured; "
                "no matching runner is currently registered.",
            )
        return (
            "set_variable",
            "Autoscaled ephemeral fleet is configured; set the runner variable "
            "to arm workflow routing.",
        )
    return "register_runner", "No registered runner has all required labels."


__all__ = ["classify_runner_route", "routing_matches"]
