"""Result validation and aggregate state for ordered QA plan execution."""

from __future__ import annotations

from typing import Any


class QaPlanExecutionError(RuntimeError):
    """A materialized plan cannot be enumerated or executed safely."""


BASELINE_GROUP_RESULTS = "baseline_group_results"
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
        "plan_id": int(case["plan_id"]),
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
    if outcome == "needs_review" or verdict in {"inconclusive", "pending"}:
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


def remember_baseline_group_results(
    cache: dict[int, dict[str, Any]],
    raw_results: Any,
) -> None:
    """Validate and add durable baseline-group results to a resume cache."""
    if not isinstance(raw_results, list):
        raise QaPlanExecutionError("baseline-group results must be a list")
    for raw in raw_results:
        if not isinstance(raw, dict):
            raise QaPlanExecutionError("baseline-group results must be objects")
        requirement_id = int(raw.get("requirement_id") or 0)
        if requirement_id < 1 or requirement_id in cache:
            raise QaPlanExecutionError(
                "baseline-group results contain invalid or duplicate requirements"
            )
        cache[requirement_id] = dict(raw)


def validated_baseline_group_results(
    group: dict[str, Any],
    *,
    anchor: dict[str, Any],
    requirements: list[dict[str, Any]],
) -> tuple[dict[int, dict[str, Any]], bool | None]:
    """Validate a host baseline executor result against the durable roster."""
    anchor_id = int(anchor["requirement_id"])
    if int(group.get("anchor_requirement_id") or 0) != anchor_id:
        raise QaPlanExecutionError(
            "baseline-group executor returned the wrong anchor requirement"
        )
    expected_ids = [
        int(case["requirement_id"])
        for case in requirements
        if case.get("executor_id") == "host_control"
        and int(case["plan_id"]) == int(anchor["plan_id"])
        and case.get("host_baseline") == anchor.get("host_baseline")
    ]
    raw_ids = group.get("requirement_ids")
    if (
        not isinstance(raw_ids, list)
        or len(raw_ids) != len(expected_ids)
        or {int(value) for value in raw_ids} != set(expected_ids)
    ):
        raise QaPlanExecutionError(
            "baseline-group executor returned membership outside the durable roster"
        )
    cache: dict[int, dict[str, Any]] = {}
    remember_baseline_group_results(cache, group.get("results"))
    if set(cache) != set(expected_ids):
        raise QaPlanExecutionError(
            "baseline-group executor omitted a durable roster result"
        )
    baseline_ok = group.get("baseline_ok")
    if baseline_ok is not None and not isinstance(baseline_ok, bool):
        raise QaPlanExecutionError(
            "baseline-group executor returned an invalid baseline outcome"
        )
    if baseline_ok is None and any(
        result.get("case_outcome") != "waiting" for result in cache.values()
    ):
        raise QaPlanExecutionError(
            "baseline-group waiting state contains a non-waiting result"
        )
    return cache, baseline_ok


def public_plan_result(result: dict[str, Any]) -> dict[str, Any]:
    """Remove resume-only baseline-group data from a public case result."""
    public = dict(result)
    public.pop(BASELINE_GROUP_RESULTS, None)
    return public


__all__ = [
    "BASELINE_GROUP_RESULTS",
    "QaPlanExecutionError",
    "aggregate_state",
    "plan_order",
    "public_plan_result",
    "remember_baseline_group_results",
    "validated_baseline_group_results",
]
