"""Release acceptance gates over scoped QA executions and canonical evidence."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from yoke_core.domain.approval_policy import parse_approval_policy
from yoke_core.domain.db_helpers import iso8601_now
from yoke_core.domain.deployment_qa_stage_acceptance import (
    acceptance_waived,
    completed_execution,
    existing_acceptance_requirement,
    latest_verdict,
    missing_execution_blocker,
)
from yoke_core.domain.deployment_qa_case_failure_kinds import failure_reasons
from yoke_core.domain.deployment_qa_stage_case_failures import (
    case_failures,
    obligations_fully_discharged,
)
from yoke_core.domain.deployment_qa_stage_outcome import (
    OUTCOME_BLOCKED,
    OUTCOME_REJECTED,
    OUTCOME_WAITING,
    answer,
    discharged,
    passed,
    settled,
    waiting,
)
from yoke_core.domain.deployment_run_unpassable_blocking_qa import (
    diagnose_unpassable_blocking_qa,
)
from yoke_core.domain.deployment_qa_stage_contract import (
    DEPLOYMENT_STAGE_ACCEPTANCE_QA_KIND,
    deployment_qa_stage_subject,
)
from yoke_core.domain.deployment_qa_execution_target import (
    deployment_qa_execution_target,
)
from yoke_core.domain.deployment_qa_admission_materialization import (
    fulfill_admitted_obligations,
)
from yoke_core.domain.post_deploy_verification_answer import (
    member_post_deploy_answer,
)
from yoke_core.domain import qa_execution_environment_target as target_authority
from yoke_core.domain.deployment_run_member_approvals import run_qa_blockers

ACCEPTANCE_QA_KIND = DEPLOYMENT_STAGE_ACCEPTANCE_QA_KIND


def _acceptance_requirement(
    conn: Any,
    *,
    subject: Mapping[str, Any],
    target: Mapping[str, Any],
) -> int:
    existing = existing_acceptance_requirement(
        conn,
        subject=subject,
        target=target,
        acceptance_qa_kind=ACCEPTANCE_QA_KIND,
    )
    if existing is not None:
        return existing
    run_id = str(subject["id"])
    stage_name = str(subject["stage"]["name"])
    member = subject.get("member_item_id")
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
            target_authority.canonical_target(target),
            target_authority.target_digest(target),
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
    from yoke_core.domain.qa_run_verdict_record import insert_qa_run

    now = iso8601_now()
    return insert_qa_run(
        conn,
        qa_requirement_id=requirement_id,
        performed_by="agent",
        qa_kind=ACCEPTANCE_QA_KIND,
        verdict=verdict,
        verdict_reason=reason,
        raw_result=json.dumps({"execution_id": execution_id}, sort_keys=True),
        started_at=now,
        completed_at=now,
        created_at=now,
    ).run_id


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
    if result.get("accepted") and member_item_id is not None:
        from yoke_core.domain.deployment_qa_member_acceptance_notice import (
            notify_item_qa_accepted,
        )

        notify_item_qa_accepted(conn, run_id=run_id, item_id=int(member_item_id))
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
    # Settle against the frozen target recorded on the run, never a live
    # environment snapshot whose URL or settings may have moved since.
    execution = completed_execution(
        conn,
        run_id=run_id,
        stage_name=stage_name,
        member_item_id=member_item_id,
        execution_target_digest=current_target_digest,
    )
    failures = tuple(
        case_failures(
            conn,
            run_id=run_id,
            stage_name=stage_name,
            member_item_id=member_item_id,
            execution_target_digest=current_target_digest,
        )
    )
    reasons = failure_reasons(failures)
    if execution is None:
        if obligations_fully_discharged(
            conn,
            run_id=run_id,
            stage_name=stage_name,
            member_item_id=member_item_id,
            execution_target_digest=current_target_digest,
        ):
            # See deployment_qa_stage_acceptance: a subject whose every case
            # is waived or superseded has nothing left to run, so the missing
            # execution is the expected end state rather than a blocker.
            return discharged()
        if member_post_deploy_answer(conn, subject).discharges_without_cases:
            # The other way a subject can have nothing left to run: the member
            # recorded, before its deploy, that it owes no post-deploy check.
            # An empty case set alone is never enough -- that is a member
            # nobody asked, which stays held.
            return discharged()
        _state, missing = missing_execution_blocker(
            conn, run_id, stage_name, member_item_id, current_target_digest
        )
        reasons.insert(0, missing)
    if reasons:
        # A missing execution alongside red cases still reads as blocked: the
        # red verdicts are the reason no acceptable execution can exist, and
        # calling that "waiting" is the collapse this split undoes.
        return _with_pin_diagnosis(conn, run_id, settled(reasons, failures))
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
        return waiting(obligation_failures)
    if blockers := run_qa_blockers(conn, run_id, member_item_id, subject):
        return waiting(blockers)
    conn.execute("SELECT id FROM deployment_runs WHERE id=%s FOR UPDATE", (run_id,))
    requirement_id = _acceptance_requirement(conn, subject=subject, target=target)
    if acceptance_waived(conn, requirement_id):
        return passed()
    latest = latest_verdict(conn, requirement_id)
    if latest == "pass":
        return passed()
    if latest == "fail":
        return answer(
            accepted=False,
            outcome=OUTCOME_REJECTED,
            reasons=[f"stage acceptance requirement #{requirement_id} was rejected"],
        )
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
        return passed()
    # The undetermined acceptance and its review request stand or fall
    # together: no review is requested against evidence a reviewer cannot
    # open, and a repaired stage re-evaluates from the same state.
    conn.execute("SAVEPOINT stage_acceptance_review")
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
    from yoke_core.domain.qa_evidence_portability import EvidenceNotPortable
    from yoke_core.domain.qa_review_requests import ensure_qa_review_request

    try:
        request, _created = ensure_qa_review_request(
            conn,
            requirement_id=requirement_id,
            run_id=review_run_id,
            policy=parse_approval_policy(
                verdict["reviewers"], path="deployment stage verdict.reviewers"
            ),
            commit=False,
        )
    except EvidenceNotPortable as exc:
        conn.execute("ROLLBACK TO SAVEPOINT stage_acceptance_review")
        conn.commit()
        return answer(accepted=False, outcome=OUTCOME_BLOCKED, reasons=[str(exc)])
    conn.commit()
    request_id = int(request["id"]) if request is not None else None
    return answer(
        accepted=False,
        outcome=OUTCOME_WAITING,
        reasons=[
            f"stage acceptance requirement #{requirement_id} awaits authorized human review"
        ],
        request_id=request_id,
    )


def _with_pin_diagnosis(
    conn: Any, run_id: str, status: dict[str, Any]
) -> dict[str, Any]:
    """Name a pin the red cases cannot pass, on the stage answer itself."""
    if status.get("outcome") != OUTCOME_BLOCKED:
        return status
    diagnosis = diagnose_unpassable_blocking_qa(conn, run_id=run_id)
    extra = list(diagnosis.notes())
    if diagnosis.unpassable:
        extra.append(diagnosis.supersede_recovery(run_id))
        reasons = [
            reason
            for reason in status["reasons"]
            if "then re-drive the run" not in reason
        ]
        return {**status, "reasons": [*reasons, *extra]}
    if not extra:
        return status
    return {**status, "reasons": [*status["reasons"], *extra]}


__all__ = [
    "ACCEPTANCE_QA_KIND",
    "deployment_qa_stage_status",
]
