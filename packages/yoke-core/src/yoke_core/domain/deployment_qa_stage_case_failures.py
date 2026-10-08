"""Which blocking cases of one deployment QA stage are not yet acceptable.

Walks the cases pinned to one stage/member subject and grades each one on
its latest verdict and the evidence behind it. What each answer *means* --
red, unrun, undetermined, or passed-without-evidence -- is
:mod:`deployment_qa_case_failure_kinds`; this module decides which of them
each case is.
"""

from __future__ import annotations

from typing import Any

from yoke_core.domain.project_identity import render_item_ref
from yoke_core.domain.db_helpers import query_rows
from yoke_core.domain.deployment_qa_case_failure_kinds import (
    CaseFailure,
    FAILURE_PASSED_WITHOUT_EVIDENCE,
    FAILURE_UNRUN,
    classify_verdict,
)
from yoke_core.domain.qa_execution_proof import qa_artifact_counts_by_run
from yoke_core.domain.qa_requirement_replacement import replacement_note
from yoke_core.domain.qa_obligation_settlement import (
    obligation_settled,
    requirement_retracted_at_select,
)


#: The blocking cases pinned to one stage/member subject, carrying both
#: discharge records so :func:`obligation_settled` can read them. That rule
#: is shared with the run-completing stage, so one boundary never re-opens
#: an obligation the other accepted as settled.
def _scoped_cases_sql(conn: Any) -> str:
    return (
        "SELECT id,plan_case_key,waived_at,superseded_by_requirement_id,replacement_requirement_id,"
        f"{requirement_retracted_at_select(conn)} "
        "FROM qa_requirements "
        "WHERE deployment_run_id=%s AND deployment_stage=%s "
        "AND COALESCE(deployment_member_item_id,0)=%s "
        "AND method_id IS NOT NULL AND blocking_mode='blocking' "
        "AND execution_target_digest=%s ORDER BY id"
    )


def scoped_cases(
    conn: Any,
    *,
    run_id: str,
    stage_name: str,
    member_item_id: int | None,
    execution_target_digest: str,
) -> list[dict[str, Any]]:
    return [
        dict(row)
        for row in query_rows(
            conn,
            _scoped_cases_sql(conn),
            (run_id, stage_name, member_item_id or 0, execution_target_digest),
        )
    ]


def obligations_fully_discharged(
    conn: Any,
    *,
    run_id: str,
    stage_name: str,
    member_item_id: int | None,
    execution_target_digest: str,
) -> bool:
    """True when this subject has cases and every one is waived or superseded.

    A subject in that state has nothing left to execute, so the absence of a
    scoped execution is the expected end state rather than a missing one. An
    empty case set is deliberately not "fully discharged": a member with no
    materialized cases has an unanswered obligation, not a settled one.
    """
    rows = scoped_cases(
        conn,
        run_id=run_id,
        stage_name=stage_name,
        member_item_id=member_item_id,
        execution_target_digest=execution_target_digest,
    )
    return bool(rows) and all(obligation_settled(row) for row in rows)


def _latest_verdicts(
    conn: Any, requirement_ids: tuple[int, ...]
) -> dict[int, tuple[int, str]]:
    """Each case's accepted run id and verdict, in one statement for the set."""
    if not requirement_ids:
        return {}
    from yoke_core.domain.qa_latest_execution import latest_executions

    rows = latest_executions(conn, requirement_ids).values()
    return {
        int(row["qa_requirement_id"]): (
            int(row["id"]),
            str(row["verdict"] or "")
            if row["completed_at"] and row["case_outcome"] not in {"running", "waiting"}
            else "",
        )
        for row in rows
    }


#: Stands in for a case set that was never materialized. It has no
#: requirement of its own to name, and no verdict, so it is ``unrun``.
NO_CASES_FAILURE = CaseFailure(
    requirement_id=0,
    plan_case_key="",
    kind=FAILURE_UNRUN,
    detail="no concrete QA cases are materialized",
)


def case_failures(
    conn: Any,
    *,
    run_id: str,
    stage_name: str,
    member_item_id: int | None,
    execution_target_digest: str,
) -> list[CaseFailure]:
    """Every blocking case this subject cannot accept, each with its kind."""
    rows = scoped_cases(
        conn,
        run_id=run_id,
        stage_name=stage_name,
        member_item_id=member_item_id,
        execution_target_digest=execution_target_digest,
    )
    if not rows:
        recorded = [
            dict(row)
            for row in query_rows(
                conn,
                "SELECT id,plan_case_key FROM qa_requirements "
                "WHERE deployment_run_id=%s AND deployment_stage=%s "
                "AND COALESCE(deployment_member_item_id,0)=%s "
                "AND method_id IS NOT NULL AND blocking_mode='blocking' "
                "AND COALESCE(execution_target_digest,'')<>'' "
                "ORDER BY id",
                (run_id, stage_name, member_item_id or 0),
            )
        ]
        if recorded:
            named = ", ".join(
                f"#{row['id']} ({row['plan_case_key']})" for row in recorded
            )
            return [
                CaseFailure(
                    requirement_id=int(recorded[0]["id"]),
                    plan_case_key=str(recorded[0]["plan_case_key"] or ""),
                    kind=FAILURE_UNRUN,
                    detail=(
                        f"member {render_item_ref(conn, member_item_id)}: recorded requirement {named} "
                        "is out of scope under the current execution target "
                        f"{execution_target_digest}; its execution remains bound "
                        "to the target it was materialized against. Reuse that "
                        "requirement — do not rematerialize a second copy."
                    ),
                )
            ]
        return [NO_CASES_FAILURE]
    # The accepted verdict, the execution results behind it, and which runs
    # carry artifacts are all questions about a requirement, and the subject's
    # requirements are already in hand — so each is asked once for the whole
    # case set rather than once per case.
    graded = tuple(int(row["id"]) for row in rows if not obligation_settled(row))
    verdicts = _latest_verdicts(conn, graded)
    runs_with_artifacts = {
        qa_run_id
        for qa_run_id, counts in qa_artifact_counts_by_run(
            conn,
            {
                candidate
                for requirement_id in graded
                for candidate in (
                    *(
                        (verdicts[requirement_id][0],)
                        if requirement_id in verdicts
                        else ()
                    ),
                )
            },
        ).items()
        if sum(counts.values())
    }
    failures: list[CaseFailure] = []
    for row in rows:
        if obligation_settled(row):
            # A superseded row is skipped rather than graded, but the case
            # that discharged it is in this same result set and is graded on
            # its own evidence. Supersession therefore moves an obligation
            # onto a named row; it never removes one from the gate.
            continue
        latest = verdicts.get(int(row["id"]))
        verdict = latest[1] if latest is not None else ""
        if verdict != "pass":
            failures.append(
                CaseFailure(
                    requirement_id=int(row["id"]),
                    plan_case_key=str(row["plan_case_key"]),
                    kind=classify_verdict(verdict),
                    detail=(
                        f"requirement #{row['id']} ({row['plan_case_key']}) latest "
                        f"verdict is {verdict or 'missing'}{replacement_note(row)}"
                    ),
                )
            )
            continue
        accepted_run_id = latest[0]
        if accepted_run_id not in runs_with_artifacts:
            looked = f"#{accepted_run_id}"
            failures.append(
                CaseFailure(
                    requirement_id=int(row["id"]),
                    plan_case_key=str(row["plan_case_key"]),
                    kind=FAILURE_PASSED_WITHOUT_EVIDENCE,
                    detail=(
                        f"requirement #{row['id']} ({row['plan_case_key']}) latest "
                        f"passing result has no attached evidence: no qa_artifacts "
                        f"on inspected qa_runs {looked} — attach evidence to "
                        f"qa_run #{accepted_run_id}, the run whose verdict was "
                        "accepted"
                    ),
                )
            )
    return failures


__all__ = [
    "NO_CASES_FAILURE",
    "case_failures",
    "obligations_fully_discharged",
    "scoped_cases",
]
