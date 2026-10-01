"""Drive serial machine partitions through the same member QA scope."""

from __future__ import annotations

from functools import wraps
from typing import Any

from yoke_core.domain.qa_plan_execution_result_state import QaPlanExecutionError


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


def execute_member_partitions(execute_one):
    """Continue only after capture, review and lease settlement have completed."""

    @wraps(execute_one)
    def execute(**kwargs):
        if not (kwargs.get("deployment_stage") and kwargs.get("deployment_member")):
            return execute_one(**kwargs)
        executions: list[str] = []
        results: list[dict[str, Any]] = []
        seen: set[int] = set()
        completed_count = 0
        while True:
            result = execute_one(**kwargs)
            if result.get("remaining_requirement_count") is None:
                return result
            execution_id = str(result.get("execution_id") or "")
            if execution_id:
                if execution_id in executions:
                    raise QaPlanExecutionError(
                        "member_machine_partition_stalled: the completed execution "
                        "was selected again with obligations remaining; report the "
                        "run, stage and member to the control-plane owner"
                    )
                executions.append(execution_id)
            for case in result.get("results") or []:
                requirement_id = int(case["requirement_id"])
                if requirement_id not in seen:
                    seen.add(requirement_id)
                    results.append(case)
            if result.get("state") != "passed" or not result.get(
                "remaining_requirement_count"
            ):
                return {
                    **result,
                    "execution_ids": executions,
                    "results": results,
                    "executed_count": len(results),
                    "requirement_count": completed_count
                    + int(result.get("requirement_count") or 0)
                    + int(result.get("remaining_requirement_count") or 0),
                }
            # A continuation preserves one stale-settled mission's host. The
            # next independent host execution starts through ordinary begin.
            completed_count += int(result.get("requirement_count") or 0)
            kwargs = {**kwargs, "continue_mission": False}

    return execute
