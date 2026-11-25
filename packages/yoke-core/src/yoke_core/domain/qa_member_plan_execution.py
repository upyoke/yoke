"""Render the settled receipt for a deployment member execution."""

from __future__ import annotations

from typing import Any


def completed_member_result(execution: dict[str, Any]) -> dict[str, Any]:
    """A member's completed scoped evidence needs no recapture or review."""
    results = [row["result"] for row in execution.get("results") or []]
    return {
        **{
            key: execution.get(key)
            for key in (
                "execution_id",
                "deployment_run_id",
                "deployment_stage",
                "deployment_member_item_id",
                "remaining_requirement_count",
            )
        },
        "state": "passed",
        "results": results,
        "requirement_count": len(execution["requirements"]),
        "executed_count": len(results),
        "review_bundle": None,
    }
