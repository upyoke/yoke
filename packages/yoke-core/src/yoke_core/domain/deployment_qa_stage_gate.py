"""Release acceptance gates over scoped QA executions and canonical evidence."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from yoke_core.domain.approval_policy import parse_approval_policy
from yoke_core.domain.db_helpers import iso8601_now
from yoke_core.domain.deployment_qa_stage_case_failures import case_failures
from yoke_core.domain.deployment_qa_stage_contract import (
    DEPLOYMENT_STAGE_ACCEPTANCE_QA_KIND,
    deployment_qa_stage_subject,
)
from yoke_core.domain.deployment_qa_execution_target import (
    deployment_qa_execution_target,
    validate_deployment_execution_target,
)
from yoke_core.domain.deployment_qa_admission_materialization import (
    fulfill_admitted_obligations,
)
from yoke_core.domain import qa_execution_environment_target as target_authority


ACCEPTANCE_QA_KIND = DEPLOYMENT_STAGE_ACCEPTANCE_QA_KIND


def _latest_verdict(conn: Any, requirement_id: int) -> str:
    row = conn.execute(
        "SELECT verdict FROM qa_runs WHERE qa_requirement_id=%s "
        "ORDER BY created_at DESC,id DESC LIMIT 1",
        (int(requirement_id),),
    ).fetchone()
    if row is None:
        return ""
    return str(row["verdict"] if hasattr(row, "keys") else row[0] or "")


def _completed_execution(
    conn: Any,
    *,
    run_id: str,
    stage_name: str,
    member_item_id: int | None,
    execution_target_digest: str,
) -> dict[str, Any] | None:
    from yoke_core.domain.qa_plan_execution_store import select_plan_execution

    row = conn.execute(
        "SELECT id FROM qa_plan_executions WHERE deployment_run_id=%s "
        "AND deployment_stage=%s "
        "AND COALESCE(deployment_member_item_id,0)=%s "
        "AND execution_target_digest=%s AND state='completed' "
        "ORDER BY created_at DESC,id DESC LIMIT 1",
        (run_id, stage_name, member_item_id or 0, execution_target_digest),
    ).fetchone()
    if row is None:
        return None
    execution_id = row["id"] if hasattr(row, "keys") else row[0]
    execution = select_plan_execution(conn, str(execution_id), lock=False)
    validate_deployment_execution_target(conn, execution)
    return execution


def _acceptance_requirement(
    conn: Any,
    *,
    subject: Mapping[str, Any],
    target: Mapping[str, Any],
) -> int:
    run_id = str(subject["id"])
    stage_name = str(subject["stage"]["name"])
    member = subject.get("member_item_id")
    rows = conn.execute(
        "SELECT id,execution_target_json,execution_target_digest "
        "FROM qa_requirements WHERE deployment_run_id=%s AND deployment_stage=%s "
        "AND COALESCE(deployment_member_item_id,0)=%s AND qa_kind=%s "
        "ORDER BY id",
        (run_id, stage_name, member or 0, ACCEPTANCE_QA_KIND),
    ).fetchall()
    expected_json = target_authority.canonical_target(target)
    expected_digest = target_authority.target_digest(target)
    matches = [
        row
        for row in rows
        if str(row["execution_target_json"] or "") == expected_json
        and str(row["execution_target_digest"] or "") == expected_digest
    ]
    if len(matches) > 1:
        raise ValueError(
            "deployment stage acceptance was materialized more than once; "
            "resolve the duplicate before resuming the pipeline"
        )
    row = matches[0] if matches else None
    if row is not None:
        stored_json = row["execution_target_json"] if hasattr(row, "keys") else row[1]
        stored_digest = (
            row["execution_target_digest"] if hasattr(row, "keys") else row[2]
        )
        if (
            str(stored_json or "") != expected_json
            or str(stored_digest or "") != expected_digest
        ):
            raise ValueError(
                "deployment stage acceptance belongs to a replaced target; "
                "preserve it and begin the replacement stage execution"
            )
        return int(row["id"] if hasattr(row, "keys") else row[0])
    now = iso8601_now()
    created = conn.execute(
        "INSERT INTO qa_requirements("
        "deployment_run_id,deployment_stage,deployment_member_item_id,"
        "qa_kind,qa_phase,blocking_mode,requirement_source,success_policy,"
        "instructions,expected_outcome,execution_target_json,"
        "execution_target_digest,created_at"
        ") VALUES (%s,%s,%s,%s,'post_deploy','blocking','flow_derived',"
        "%s,%s,%s,%s,%s,%s) RETURNING id",
        (
            run_id,
            stage_name,
            member,
            ACCEPTANCE_QA_KIND,
            json.dumps(
                subject["stage"]["verdict"], sort_keys=True, separators=(",", ":")
            ),
            "Review the completed scoped deployment QA cases and their evidence.",
            "Every admitted case passed against the pinned deployment target.",
            expected_json,
            expected_digest,
            now,
        ),
    ).fetchone()
    return int(created["id"] if hasattr(created, "keys") else created[0])


def _record_acceptance(
    conn: Any,
    *,
    requirement_id: int,
    execution_id: str,
    verdict: str,
    reason: str,
) -> int:
    now = iso8601_now()
    row = conn.execute(
        "INSERT INTO qa_runs("
        "qa_requirement_id,performed_by,qa_kind,verdict,verdict_reason,"
        "raw_result,started_at,completed_at,created_at"
        ") VALUES (%s,'agent',%s,%s,%s,%s,%s,%s,%s) RETURNING id",
        (
            requirement_id,
            ACCEPTANCE_QA_KIND,
            verdict,
            reason,
            json.dumps({"execution_id": execution_id}, sort_keys=True),
            now,
            now,
            now,
        ),
    ).fetchone()
    return int(row["id"] if hasattr(row, "keys") else row[0])


def deployment_qa_stage_status(
    conn: Any,
    *,
    run_id: str,
    stage_name: str,
    member_item_id: int | None,
) -> dict[str, Any]:
    """Settle or describe one stage/member acceptance boundary.

    ``target_digest`` rides along: stable while this is the same wait,
    different when the stage's own pinned target identity changes within
    an existing retry/requirement contract -- the identity a wake notice's
    own key needs to tell the two apart. It never authorizes swapping a
    frozen run's candidate or membership in place; that stays a
    replacement run's job.
    """
    subject = deployment_qa_stage_subject(
        conn,
        run_id=run_id,
        stage_name=stage_name,
        member_item_id=member_item_id,
    )
    target = deployment_qa_execution_target(conn, subject)
    digest = target_authority.target_digest(target)
    result = _settle_stage_status(
        conn,
        subject=subject,
        target=target,
        run_id=run_id,
        stage_name=stage_name,
        member_item_id=member_item_id,
    )
    result["target_digest"] = digest
    return result


def _settle_stage_status(
    conn: Any,
    *,
    subject: Mapping[str, Any],
    target: Mapping[str, Any],
    run_id: str,
    stage_name: str,
    member_item_id: int | None,
) -> dict[str, Any]:
    """Settle or describe one active stage/member acceptance boundary."""
    current_target_digest = target_authority.target_digest(target)
    execution = _completed_execution(
        conn,
        run_id=run_id,
        stage_name=stage_name,
        member_item_id=member_item_id,
        execution_target_digest=current_target_digest,
    )
    failures = case_failures(
        conn,
        run_id=run_id,
        stage_name=stage_name,
        member_item_id=member_item_id,
        execution_id=str(execution["id"]) if execution is not None else None,
        execution_target_digest=current_target_digest,
    )
    if execution is None:
        failures.insert(0, "no completed scoped QA execution exists")
    if failures:
        return {"accepted": False, "reasons": failures, "request_id": None}
    assert execution is not None
    obligation_failures = fulfill_admitted_obligations(
        conn,
        run_id=run_id,
        stage_name=stage_name,
        member_item_id=member_item_id,
        execution_id=str(execution["id"]),
        execution_target_digest=current_target_digest,
        acceptance_qa_kind=ACCEPTANCE_QA_KIND,
    )
    if obligation_failures:
        return {
            "accepted": False,
            "reasons": obligation_failures,
            "request_id": None,
        }
    conn.execute("SELECT id FROM deployment_runs WHERE id=%s FOR UPDATE", (run_id,))
    requirement_id = _acceptance_requirement(conn, subject=subject, target=target)
    waiver_row = conn.execute(
        "SELECT waived_at FROM qa_requirements WHERE id=%s", (requirement_id,)
    ).fetchone()
    waived_at = (
        waiver_row["waived_at"] if hasattr(waiver_row, "keys") else waiver_row[0]
    )
    if waived_at:
        return {"accepted": True, "reasons": [], "request_id": None}
    latest = _latest_verdict(conn, requirement_id)
    if latest == "pass":
        return {"accepted": True, "reasons": [], "request_id": None}
    if latest == "fail":
        return {
            "accepted": False,
            "reasons": [f"stage acceptance requirement #{requirement_id} was rejected"],
            "request_id": None,
        }
    verdict = subject["stage"]["verdict"]
    mode = str(verdict["mode"])
    if mode in {"agent_only", "human_if_unsure"}:
        _record_acceptance(
            conn,
            requirement_id=requirement_id,
            execution_id=str(execution["id"]),
            verdict="pass",
            reason=f"all scoped cases passed under {mode}",
        )
        conn.commit()
        return {"accepted": True, "reasons": [], "request_id": None}
    if latest != "undetermined":
        review_run_id = _record_acceptance(
            conn,
            requirement_id=requirement_id,
            execution_id=str(execution["id"]),
            verdict="undetermined",
            reason="configured deployment stage requires authorized human acceptance",
        )
    else:
        row = conn.execute(
            "SELECT id FROM qa_runs WHERE qa_requirement_id=%s "
            "ORDER BY created_at DESC,id DESC LIMIT 1",
            (requirement_id,),
        ).fetchone()
        review_run_id = int(row["id"] if hasattr(row, "keys") else row[0])
    from yoke_core.domain.qa_review_requests import ensure_qa_review_request

    request, _created = ensure_qa_review_request(
        conn,
        requirement_id=requirement_id,
        run_id=review_run_id,
        policy=parse_approval_policy(
            verdict["reviewers"], path="deployment stage verdict.reviewers"
        ),
        commit=False,
    )
    conn.commit()
    request_id = int(request["id"]) if request is not None else None
    return {
        "accepted": False,
        "reasons": [
            f"stage acceptance requirement #{requirement_id} awaits authorized human review"
        ],
        "request_id": request_id,
    }


__all__ = ["ACCEPTANCE_QA_KIND", "deployment_qa_stage_status"]
