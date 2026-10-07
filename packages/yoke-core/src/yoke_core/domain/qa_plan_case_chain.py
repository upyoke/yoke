"""Chains of machine-run cases inside one ordered QA plan execution.

A case that starts from a named baseline or runs ``as_is`` opens a chain; the
``inherit`` cases right behind it in the roster, at the same plan and
baseline position, continue on the machine it left. The roster runs every
case of a baseline position before the next position, so a chain is always a
contiguous run of roster rows.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from yoke_contracts.qa_case_starting_state import INHERIT

INHERITED_PREDECESSOR_NOT_PASSED = "inherited_predecessor_not_passed"


def _continues(previous: Mapping[str, Any], case: Mapping[str, Any]) -> bool:
    return (
        case.get("starting_state") == INHERIT
        and previous.get("plan_id") == case.get("plan_id")
        and previous.get("baseline_position") == case.get("baseline_position")
    )


def ends_chain(roster: Sequence[Mapping[str, Any]], ordinal: int) -> bool:
    """Whether no later roster case inherits the machine this case leaves."""
    if ordinal + 1 >= len(roster):
        return True
    return not _continues(roster[ordinal], roster[ordinal + 1])


def _plan_predecessor_id(conn: Any, case: Mapping[str, Any]) -> int | None:
    """The requirement materialized from the plan case this one inherits from.

    Waived rows count: a predecessor waived out of the roster still left the
    machine unvisited, and its follower must not run as if it had.
    """
    from yoke_core.domain.db_helpers import query_one
    from yoke_core.domain.qa_obligation_settlement import unanswered_attempt_sql
    from yoke_core.domain.qa_plan_execution_store import marker

    p = marker(conn)
    subjects = [
        column
        for column in ("item_id", "deployment_run_id", "standalone_execution_id")
        if case.get(column) is not None
    ]
    if len(subjects) != 1:
        return None
    row = query_one(
        conn,
        "SELECT id FROM qa_requirements "
        f"WHERE {subjects[0]}={p} AND plan_id={p} AND baseline_position={p} "
        f"AND case_position<{p} "
        f"AND COALESCE(workflow_transition_id,'')={p} "
        f"AND COALESCE(deployment_stage,'')={p} "
        f"AND COALESCE(deployment_member_item_id,0)={p} "
        f"AND COALESCE(execution_target_digest,'')={p} "
        f"AND {unanswered_attempt_sql(conn)} "
        "ORDER BY case_position DESC, id DESC LIMIT 1",
        (
            case[subjects[0]],
            int(case["plan_id"]),
            int(case["baseline_position"]),
            int(case["case_position"]),
            str(case.get("workflow_transition_id") or ""),
            str(case.get("deployment_stage") or ""),
            int(case.get("deployment_member_item_id") or 0),
            str(case.get("execution_target_digest") or ""),
        ),
    )
    return int(row["id"]) if row is not None else None


def inherit_blocker(
    conn: Any,
    execution: Mapping[str, Any],
    case: Mapping[str, Any],
    *,
    ordinal: int,
) -> dict[str, Any] | None:
    """Why an inheriting case cannot run, or ``None`` when it may.

    It may run only directly after its plan predecessor, in this same plan
    execution, once that predecessor passed.
    """
    if case.get("starting_state") != INHERIT:
        return None
    from yoke_core.domain.qa_plan_execution_store import result_rows

    roster = execution["roster"]
    previous = roster[ordinal - 1] if ordinal > 0 else None
    predecessor_id = _plan_predecessor_id(conn, case)
    blocker = {
        "predecessor_requirement_id": predecessor_id,
        "predecessor_case_key": previous.get("case_key") if previous else None,
    }
    if (
        previous is None
        or predecessor_id is None
        or int(previous["requirement_id"]) != predecessor_id
        or not _continues(previous, case)
    ):
        blocker["reason"] = (
            f"case {case['case_key']!r} inherits the machine of the case "
            "before it in its plan, but that case "
            f"(requirement {predecessor_id}) did not run directly before it "
            "in this plan run"
        )
        return blocker
    outcome = next(
        (
            (row["result"] or {}).get("case_outcome")
            for row in result_rows(conn, str(execution["id"]))
            if int(row["ordinal"]) == ordinal - 1
        ),
        None,
    )
    if outcome == "passed":
        return None
    blocker["predecessor_case_outcome"] = outcome
    blocker["reason"] = (
        f"case {case['case_key']!r} inherits the machine case "
        f"{previous['case_key']!r} (requirement {predecessor_id}) left, and "
        f"that case did not pass (outcome {outcome!r}); it was not run"
    )
    return blocker


def record_blocked_case(
    conn: Any,
    execution: Mapping[str, Any],
    case: dict[str, Any],
    *,
    ordinal: int,
    blocker: Mapping[str, Any],
) -> dict[str, Any]:
    """Record an inheriting case as blocked without touching the machine."""
    from yoke_core.domain.handlers.machine_qa_case_evidence import (
        record_machine_case_result,
    )
    from yoke_core.domain.machine_qa_case_result import MachineCaseResult
    from yoke_core.domain.machine_qa_execution_protocol import (
        commit_deferred_connection,
    )
    from yoke_core.domain.qa_plan_execution_result_state import plan_order
    from yoke_core.domain.qa_plan_execution_state import advance_plan_execution

    result = record_machine_case_result(
        commit_deferred_connection(conn),
        case=case,
        result=MachineCaseResult(
            case_outcome="blocked_on_precondition",
            verdict="blocked",
            evidence={
                "runner_id": case["runner_id"],
                "case_started": False,
                "starting_state": INHERIT,
                "inherit_blocker": dict(blocker),
            },
            error_code=INHERITED_PREDECESSOR_NOT_PASSED,
        ),
        duration_ms=0,
    )
    normalized = {**plan_order(case), **result, "error": blocker["reason"]}
    advance_plan_execution(
        conn,
        dict(execution),
        ordinal=ordinal,
        requirement_id=int(case["requirement_id"]),
        result=normalized,
        commit=False,
    )
    return normalized


__all__ = [
    "INHERITED_PREDECESSOR_NOT_PASSED",
    "ends_chain",
    "inherit_blocker",
    "record_blocked_case",
]
