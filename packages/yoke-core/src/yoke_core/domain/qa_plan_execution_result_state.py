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
    # The run removed this member mid-case: QA was cancelled, not judged.
    "removed": 6,
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
    if outcome == "removed":
        result_state = "removed"
    if _PLAN_STATE_PRECEDENCE[result_state] > _PLAN_STATE_PRECEDENCE[current]:
        return result_state
    return current


def case_failed(result: dict[str, Any]) -> bool:
    """Whether this one case failed, errored or lost its capture.

    Such a case closes the execution once every independent chain has run;
    the cases chained behind it are recorded blocked, never run.
    """
    return (
        aggregate_state("passed", result) in {"failed", "error"}
        or result.get("execution_status") == "capture_failed"
    )


def plan_recovery(
    state: str, failed_cases: list[int], results: list[dict], *, raised: bool
) -> str | None:
    if state == "waiting" and results:
        return results[-1].get("recovery")
    if state == "removed":
        return (
            "The deployment run removed this item while its QA was running, so "
            "the execution was cancelled with nothing recorded as passed; no "
            "host needs repair. The item owes its QA in its next release."
        )
    if state not in {"failed", "error"}:
        return None
    rerun = (
        "Correct the case or plan and rerun yoke qa plan run; "
        "no manual abort is needed."
    )
    if raised or not failed_cases:
        return f"QA execution closed after a case raised while running. {rerun}"
    named = ", ".join(str(requirement_id) for requirement_id in failed_cases)
    return (
        f"QA execution ran every independent chain and closed after failed "
        f"case requirements {named}. Cases chained behind a failed case are "
        f"recorded blocked (inherited_predecessor_not_passed) and did not run. "
        f"{rerun}"
    )


__all__ = [
    "QaPlanExecutionError",
    "aggregate_state",
    "case_failed",
    "plan_order",
    "plan_recovery",
]
