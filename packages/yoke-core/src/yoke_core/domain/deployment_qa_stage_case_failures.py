"""Which blocking cases of one deployment QA stage are not yet acceptable.

Walks the cases pinned to one stage/member subject and grades each one on
its latest verdict and the evidence behind it. What each answer *means* --
red, unrun, undetermined, or passed-without-evidence -- is
:mod:`deployment_qa_case_failure_kinds`; this module decides which of them
each case is.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from yoke_core.domain.db_helpers import query_rows
from yoke_core.domain.deployment_qa_case_failure_kinds import (
    CaseFailure,
    FAILURE_PASSED_WITHOUT_EVIDENCE,
    FAILURE_UNRUN,
    classify_verdict,
)
from yoke_core.domain.qa_execution_proof import qa_artifact_counts_by_run
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
        "SELECT id,plan_case_key,waived_at,superseded_by_requirement_id,"
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


#: A case's evidence as the execution record names it: any completed
#: execution of this same subject and target rather than one chosen
#: execution. A corrected case typically runs under its own plan, and
#: therefore its own execution; reading only the newest execution's results
#: made that passing case report "no attached evidence" and hold the stage it
#: had just satisfied. This is the fallback behind the accepted verdict's own
#: run. The digest predicate still carries the target-identity guarantee, so
#: evidence recorded against a replaced target is no more visible than before.
_CASE_EVIDENCE_SQL = (
    "SELECT r.requirement_id,r.result_json FROM qa_plan_execution_results r "
    "JOIN qa_plan_executions e ON e.id=r.execution_id "
    "WHERE r.requirement_id IN ({placeholders}) AND e.deployment_run_id=%s "
    "AND e.deployment_stage=%s "
    "AND COALESCE(e.deployment_member_item_id,0)=%s "
    "AND e.execution_target_digest=%s AND e.state='completed' "
    "ORDER BY r.requirement_id,r.completed_at DESC,r.ordinal DESC"
)

#: Each case's accepted verdict and the run that carries it, for the whole
#: case set at once. A subject's cases are known before any of them is
#: graded, so this is one statement per subject rather than one per case.
_LATEST_VERDICTS_SQL = (
    "SELECT DISTINCT ON (qa_requirement_id) qa_requirement_id,id,verdict "
    "FROM qa_runs WHERE qa_requirement_id IN ({placeholders}) "
    "ORDER BY qa_requirement_id,created_at DESC,id DESC"
)


def _placeholders(values: tuple[int, ...]) -> str:
    return ",".join("%s" for _ in values)


def _latest_verdicts(
    conn: Any, requirement_ids: tuple[int, ...]
) -> dict[int, tuple[int, str]]:
    """Each case's accepted run id and verdict, in one statement for the set."""
    if not requirement_ids:
        return {}
    rows = query_rows(
        conn,
        _LATEST_VERDICTS_SQL.format(placeholders=_placeholders(requirement_ids)),
        requirement_ids,
    )
    return {
        int(row["qa_requirement_id"]): (int(row["id"]), str(row["verdict"] or ""))
        for row in rows
    }


def _execution_evidence_runs(
    conn: Any,
    requirement_ids: tuple[int, ...],
    *,
    run_id: str,
    stage_name: str,
    member_item_id: int | None,
    execution_target_digest: str,
) -> dict[int, list[int]]:
    """Per case, the run ids its completed execution results name, in order."""
    if not requirement_ids:
        return {}
    rows = query_rows(
        conn,
        _CASE_EVIDENCE_SQL.format(placeholders=_placeholders(requirement_ids)),
        (
            *requirement_ids,
            run_id,
            stage_name,
            member_item_id or 0,
            execution_target_digest,
        ),
    )
    grouped: dict[int, list[int]] = {}
    for row in rows:
        raw_result = row["result_json"]
        result = (
            dict(raw_result)
            if isinstance(raw_result, Mapping)
            else json.loads(str(raw_result or "{}"))
        )
        evidence_run_id = result.get("qa_run_id") or result.get("run_id")
        if evidence_run_id is not None:
            grouped.setdefault(int(row["requirement_id"]), []).append(
                int(evidence_run_id)
            )
    return grouped


def _inspect_evidence(
    candidates: list[int],
    runs_with_artifacts: set[int],
) -> tuple[bool, list[int]]:
    """Whether any candidate run carries artifacts, and the runs inspected.

    The run whose verdict this gate accepted is inspected first, because that
    is the run the gate's evidence question is about and the one a reviewer
    attaches evidence to. Asking only the execution record instead named a
    different run — the capture run the execution wrote — and refused a member
    whose evidence was already attached where the accepted pass lived. The
    execution-scoped walk stays behind it, so a corrected case that ran under
    its own plan and execution keeps passing on that evidence.

    The inspected ids are returned so a refusal can say where it looked.
    """
    inspected: list[int] = []
    for candidate in candidates:
        if candidate in inspected:
            continue
        inspected.append(candidate)
        if candidate in runs_with_artifacts:
            return True, inspected
    return False, inspected


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
                        f"member {member_item_id}: recorded requirement {named} "
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
    evidence = _execution_evidence_runs(
        conn,
        graded,
        run_id=run_id,
        stage_name=stage_name,
        member_item_id=member_item_id,
        execution_target_digest=execution_target_digest,
    )
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
                    *evidence.get(requirement_id, []),
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
                        f"verdict is {verdict or 'missing'}"
                    ),
                )
            )
            continue
        accepted_run_id = latest[0]
        found, inspected = _inspect_evidence(
            [accepted_run_id, *evidence.get(int(row["id"]), [])],
            runs_with_artifacts,
        )
        if not found:
            looked = ", ".join(f"#{candidate}" for candidate in inspected)
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
