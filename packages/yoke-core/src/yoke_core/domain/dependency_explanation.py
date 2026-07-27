"""Human-readable dependency edge explanations."""

from __future__ import annotations

from typing import Optional


def explain_dependency(
    gate_point: str,
    satisfaction: str,
    blocking_item: str,
    blocking_status: Optional[str] = None,
    rationale: Optional[str] = None,
) -> str:
    """Generate a human-readable explanation of a dependency."""
    sat_desc = {
        "status:done": "status reaches done",
        "status:implemented": "status reaches implemented",
        "fact:merged": "branch is merged to main",
    }.get(satisfaction, satisfaction)

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


__all__ = ["explain_dependency"]
