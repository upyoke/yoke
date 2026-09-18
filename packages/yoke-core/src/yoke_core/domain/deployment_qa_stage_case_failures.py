"""Per-case failure reasons for one deployment QA stage acceptance check."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from yoke_core.domain.db_helpers import query_rows


#: The blocking cases pinned to one stage/member subject, with both ways an
#: obligation can already be discharged. Waiver and supersession are read
#: together because the gate treats them the same way -- as an obligation it
#: no longer has to see evidence for -- while the records stay distinct so a
#: reader can always tell which one happened.
_SCOPED_CASES_SQL = (
    "SELECT id,plan_case_key,waived_at,superseded_by_requirement_id "
    "FROM qa_requirements "
    "WHERE deployment_run_id=%s AND deployment_stage=%s "
    "AND COALESCE(deployment_member_item_id,0)=%s "
    "AND method_id IS NOT NULL AND blocking_mode='blocking' "
    "AND execution_target_digest=%s ORDER BY id"
)


def _discharged(row: Mapping[str, Any]) -> bool:
    """True when this case's obligation is already settled without evidence."""
    return bool(row["waived_at"]) or bool(row["superseded_by_requirement_id"])


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
    return bool(rows) and all(_discharged(row) for row in rows)


#: A case's evidence, found through any completed execution of this same
#: subject and target rather than through one chosen execution. A corrected
#: case typically runs under its own plan, and therefore its own execution;
#: reading only the newest execution's results made that passing case report
#: "no attached evidence" and hold the stage it had just satisfied. The
#: digest predicate still carries the target-identity guarantee, so evidence
#: recorded against a replaced target is no more visible than before.
_CASE_EVIDENCE_SQL = (
    "SELECT r.result_json FROM qa_plan_execution_results r "
    "JOIN qa_plan_executions e ON e.id=r.execution_id "
    "WHERE r.requirement_id=%s AND e.deployment_run_id=%s "
    "AND e.deployment_stage=%s "
    "AND COALESCE(e.deployment_member_item_id,0)=%s "
    "AND e.execution_target_digest=%s AND e.state='completed' "
    "ORDER BY r.completed_at DESC,r.ordinal DESC"
)


def _has_evidence(
    conn: Any,
    *,
    requirement_id: int,
    run_id: str,
    stage_name: str,
    member_item_id: int | None,
    execution_target_digest: str,
) -> bool:
    """True when some completed execution of this subject attached artifacts."""
    rows = query_rows(
        conn,
        _CASE_EVIDENCE_SQL,
        (
            int(requirement_id),
            run_id,
            stage_name,
            member_item_id or 0,
            execution_target_digest,
        ),
    )
    for row in rows:
        raw_result = row["result_json"]
        result = (
            dict(raw_result)
            if isinstance(raw_result, Mapping)
            else json.loads(str(raw_result or "{}"))
        )
        evidence_run_id = result.get("qa_run_id") or result.get("run_id")
        if evidence_run_id is None:
            continue
        attached = int(
            conn.execute(
                "SELECT COUNT(*) FROM qa_artifacts WHERE qa_run_id=%s",
                (int(evidence_run_id),),
            ).fetchone()[0]
        )
        if attached:
            return True
    return False


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
        if _discharged(row):
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
        if not _has_evidence(
            conn,
            requirement_id=int(row["id"]),
            run_id=run_id,
            stage_name=stage_name,
            member_item_id=member_item_id,
            execution_target_digest=execution_target_digest,
        ):
            failures.append(
                f"requirement #{row['id']} ({row['plan_case_key']}) latest "
                "passing result has no attached evidence"
            )
    return failures


__all__ = ["case_failures", "obligations_fully_discharged", "scoped_cases"]
