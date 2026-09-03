"""Human-readable dependency edge explanations."""

from __future__ import annotations

from typing import Optional

from yoke_core.domain.dependency_types import deployed_environment


def satisfaction_description(satisfaction: str) -> str:
    """Render status values, fact:merged, or fact:deployed:<environment-name>."""
    environment = deployed_environment(satisfaction)
    if environment is not None:
        return f"deployment to {environment}"
    return {
        "status:done": "status reaches done",
        "status:implemented": "status reaches implemented",
        "fact:merged": "branch is merged to main",
    }.get(satisfaction, satisfaction)


def dependency_wait_summary(
    blocking_item: str,
    satisfaction: str,
    reason: str = "",
) -> str:
    """Render the blocker, including a deployed environment when present."""
    environment = deployed_environment(satisfaction)
    if environment is not None:
        summary = f"Waits for {blocking_item} to deploy to {environment}"
    else:
        summary = f"Blocked by {blocking_item} (requires {satisfaction})"
    return f"{summary}: {reason}" if reason else summary


def explain_dependency(
    gate_point: str,
    satisfaction: str,
    blocking_item: str,
    blocking_status: Optional[str] = None,
    rationale: Optional[str] = None,
) -> str:
    """Generate a human-readable explanation of a dependency."""
    sat_desc = satisfaction_description(satisfaction)

    gate_desc = {
        "activation": "blocks activation",
        "integration": "blocks integration (merge ordering)",
        "closure": "blocks closure",
    }.get(gate_point, f"blocks at {gate_point}")

    parts = [blocking_item, gate_desc, f"(satisfied when: {sat_desc})"]
    if blocking_status:
        parts.append(f"[current: {blocking_status}]")
    if rationale:
        parts.append(f"-- {rationale}")
    return " ".join(parts)


__all__ = [
    "dependency_wait_summary",
    "explain_dependency",
    "satisfaction_description",
]
