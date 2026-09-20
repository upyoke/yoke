"""Per-case failure reasons for one deployment QA stage acceptance check."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from yoke_core.domain.db_helpers import query_rows
from yoke_core.domain.qa_obligation_settlement import obligation_settled


#: The blocking cases pinned to one stage/member subject, carrying both
#: discharge records so :func:`obligation_settled` can read them. That rule
#: is shared with the run-completing stage, so one boundary never re-opens
#: an obligation the other accepted as settled.
_SCOPED_CASES_SQL = (
    "SELECT id,plan_case_key,waived_at,superseded_by_requirement_id "
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
            _SCOPED_CASES_SQL,
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
    "SELECT r.result_json FROM qa_plan_execution_results r "
    "JOIN qa_plan_executions e ON e.id=r.execution_id "
    "WHERE r.requirement_id=%s AND e.deployment_run_id=%s "
    "AND e.deployment_stage=%s "
    "AND COALESCE(e.deployment_member_item_id,0)=%s "
    "AND e.execution_target_digest=%s AND e.state='completed' "
    "ORDER BY r.completed_at DESC,r.ordinal DESC"
)


def _artifact_count(conn: Any, qa_run_id: int) -> int:
    return int(
        conn.execute(
            "SELECT COUNT(*) FROM qa_artifacts WHERE qa_run_id=%s",
            (int(qa_run_id),),
        ).fetchone()[0]
    )


def _execution_evidence_runs(
    conn: Any,
    *,
    requirement_id: int,
    run_id: str,
    stage_name: str,
    member_item_id: int | None,
    execution_target_digest: str,
) -> list[int]:
    """The run ids this subject's completed execution results name."""
    runs: list[int] = []
    for row in query_rows(
        conn,
        _CASE_EVIDENCE_SQL,
        (
            int(requirement_id),
            run_id,
            stage_name,
            member_item_id or 0,
            execution_target_digest,
        ),
    ):
        raw_result = row["result_json"]
        result = (
            dict(raw_result)
            if isinstance(raw_result, Mapping)
            else json.loads(str(raw_result or "{}"))
        )
        evidence_run_id = result.get("qa_run_id") or result.get("run_id")
        if evidence_run_id is not None:
            runs.append(int(evidence_run_id))
    return runs


def _inspect_evidence(
    conn: Any,
    *,
    verdict_run_id: int,
    requirement_id: int,
    run_id: str,
    stage_name: str,
    member_item_id: int | None,
    execution_target_digest: str,
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
    candidates = [
        verdict_run_id,
        *_execution_evidence_runs(
            conn,
            requirement_id=requirement_id,
            run_id=run_id,
            stage_name=stage_name,
            member_item_id=member_item_id,
            execution_target_digest=execution_target_digest,
        ),
    ]
    inspected: list[int] = []
    for candidate in candidates:
        if candidate in inspected:
            continue
        inspected.append(candidate)
        if _artifact_count(conn, candidate):
            return True, inspected
    return False, inspected


def case_failures(
    conn: Any,
    *,
    run_id: str,
    stage_name: str,
    member_item_id: int | None,
    execution_target_digest: str,
) -> list[str]:
    rows = scoped_cases(
        conn,
        run_id=run_id,
        stage_name=stage_name,
        member_item_id=member_item_id,
        execution_target_digest=execution_target_digest,
    )
    if not rows:
        return ["no concrete QA cases are materialized"]
    failures: list[str] = []
    for row in rows:
        if obligation_settled(row):
            # A superseded row is skipped rather than graded, but the case
            # that discharged it is in this same result set and is graded on
            # its own evidence. Supersession therefore moves an obligation
            # onto a named row; it never removes one from the gate.
            continue
        latest = conn.execute(
            "SELECT id,verdict FROM qa_runs WHERE qa_requirement_id=%s "
            "ORDER BY created_at DESC,id DESC LIMIT 1",
            (int(row["id"]),),
        ).fetchone()
        verdict = str(latest["verdict"] if latest is not None else "")
        if verdict != "pass":
            failures.append(
                f"requirement #{row['id']} ({row['plan_case_key']}) latest "
                f"verdict is {verdict or 'missing'}"
            )
            continue
        accepted_run_id = int(latest["id"])
        found, inspected = _inspect_evidence(
            conn,
            verdict_run_id=accepted_run_id,
            requirement_id=int(row["id"]),
            run_id=run_id,
            stage_name=stage_name,
            member_item_id=member_item_id,
            execution_target_digest=execution_target_digest,
        )
        if not found:
            looked = ", ".join(f"#{candidate}" for candidate in inspected)
            failures.append(
                f"requirement #{row['id']} ({row['plan_case_key']}) latest "
                f"passing result has no attached evidence: no qa_artifacts on "
                f"inspected qa_runs {looked} — attach evidence to qa_run "
                f"#{accepted_run_id}, the run whose verdict was accepted"
            )
    return failures


__all__ = ["case_failures", "obligations_fully_discharged", "scoped_cases"]
