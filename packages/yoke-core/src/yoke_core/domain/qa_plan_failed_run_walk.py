"""Close a run whose cases failed, unless its prepared missions still walk.

A standalone execution has no other way to walk a mission: its requirements
belong to that one execution, so closing it before the walk strands every
mission as needs_review. When an independent mission chain prepared cleanly,
the run enters review like a clean run instead; the failed cases keep their
recorded outcomes, and the review submission settles the execution as failed
and names them. Item and deployment runs keep closing on the failure: their
missions rerun alone through ``yoke qa case run --requirement-id``.
"""

from __future__ import annotations

from typing import Any, Callable, Mapping, Sequence

from yoke_contracts.qa_case_starting_state import needs_test_machine
from yoke_core.domain.qa_plan_execution_abort_reason import case_failed_reason
from yoke_core.domain.qa_plan_execution_result_state import aggregate_state


def walks_past_failures(
    execution: Mapping[str, Any],
    requirements: Sequence[Mapping[str, Any]],
    results: Sequence[Mapping[str, Any]],
) -> bool:
    """Whether a standalone run holds a cleanly prepared mission to walk."""
    if not execution.get("standalone_plan_id"):
        return False
    missions = {
        int(case["requirement_id"])
        for case in requirements
        if case.get("runner_id") == "agent_mission" and needs_test_machine(case)
    }
    return any(
        int(row.get("requirement_id") or 0) in missions
        and aggregate_state("passed", dict(row)) == "needs_review"
        for row in results
    )


def close_failed_run(
    call: Callable[..., Any],
    *,
    target: Any,
    execution_id: str,
    failed_cases: list[int],
    actor: Any,
    state: str,
) -> str:
    """Abort the execution naming its failed cases; return the plan state."""
    call(
        function_id="qa.plan_execution.abort",
        target=target,
        payload={
            "execution_id": execution_id,
            "reason": case_failed_reason(failed_cases),
        },
        actor=actor,
    )
    return state if state in {"failed", "error"} else "failed"


__all__ = ["close_failed_run", "walks_past_failures"]
