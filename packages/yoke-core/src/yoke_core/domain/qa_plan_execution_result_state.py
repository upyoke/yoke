"""Result validation and aggregate state for ordered QA plan execution."""

from __future__ import annotations

from typing import Any


class QaPlanExecutionError(RuntimeError):
    """A materialized plan cannot be enumerated or executed safely."""


_PLAN_STATE_PRECEDENCE = {
    "passed": 0,
    "needs_review": 1,
    "blocked_on_precondition": 2,
    "failed": 3,
    "waiting": 4,
    "error": 5,
}


def plan_order(case: dict[str, Any]) -> dict[str, Any]:
    """Return the immutable ordering fields persisted with a case result."""
    return {
        "plan_id": (int(case["plan_id"]) if case.get("plan_id") is not None else None),
        "case_key": str(case["case_key"]),
        "case_position": int(case["case_position"]),
        "baseline_position": int(case["baseline_position"]),
        "host_baseline": case.get("host_baseline"),
    }


def aggregate_state(current: str, result: dict[str, Any]) -> str:
    """Fold one case result into the plan's highest-precedence state."""
    outcome = str(result.get("case_outcome") or "")
    verdict = str(result.get("verdict") or "")
    result_state = "passed"
    if outcome == "needs_review" or verdict in {"undetermined", "pending"}:
        result_state = "needs_review"
    if outcome == "blocked_on_precondition":
        result_state = "blocked_on_precondition"
    if outcome == "failed" or verdict == "fail":
        result_state = "failed"
    if outcome == "waiting" or verdict == "waiting":
        result_state = "waiting"
    if outcome == "error" or verdict == "error":
        result_state = "error"
    if _PLAN_STATE_PRECEDENCE[result_state] > _PLAN_STATE_PRECEDENCE[current]:
        return result_state
    return current


__all__ = [
    "QaPlanExecutionError",
    "aggregate_state",
    "plan_order",
]
