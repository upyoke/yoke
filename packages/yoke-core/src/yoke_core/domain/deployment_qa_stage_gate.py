"""Release acceptance gates over scoped QA executions and canonical evidence."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from yoke_core.domain.db_helpers import instant_parameter, utc_now
from yoke_core.domain.deployment_qa_stage_acceptance import (
    existing_acceptance_requirement,
    completed_execution,
    missing_execution_blocker,
    member_cases_passed,
)
from yoke_core.domain.deployment_qa_acceptance_reads import stopped_case_execution
from yoke_core.domain.deployment_qa_case_failure_kinds import failure_reasons
from yoke_core.domain.deployment_qa_stage_case_failures import (
    case_failures,
    obligations_fully_discharged,
)
from yoke_core.domain.deployment_qa_stage_outcome import (
    OUTCOME_BLOCKED,
    OUTCOME_DISCHARGED,
    discharged,
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
    NOT_REQUIRED,
    member_post_deploy_answer,
)
from yoke_core.domain import qa_execution_environment_target as target_authority
from yoke_core.domain.deployment_run_member_approvals import run_qa_blockers
from yoke_core.domain.deployment_qa_presentation_facts import run_presentation
from yoke_core.domain.deployment_qa_presentation_reads import presentation_operation
from yoke_core.domain.deployment_qa_stage_acceptance_write import (
    Acceptance,
    write_status as _write_status,
)

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
    now = instant_parameter(conn, utc_now())
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


def deployment_qa_stage_status(
    conn: Any,
    *,
    run_id: str,
    stage_name: str,
    member_item_id: int | None,
    notify_acceptance: bool = True,
) -> dict[str, Any]:
    """Settle or describe one stage/member acceptance boundary.

    An accepted member is closed out through its acceptance notice.
    ``notify_acceptance=False`` leaves that to the caller, so a stage walk
    can wake every waiting owner before any slower member close-out.

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
    if notify_acceptance and result.get("accepted") and member_item_id is not None:
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
    """Settle or describe one active stage/member acceptance boundary.

    Every read happens first, as one set per fact across the run's members;
    the run row lock covers only each acceptance write.
    """
    read = _read_settlement(
        conn,
        subject=subject,
        target=target,
        run_id=run_id,
        stage_name=stage_name,
        member_item_id=member_item_id,
    )
    from yoke_core.domain.deployment_qa_presentation_reads import uncached_presentation

    with uncached_presentation():
        if isinstance(read, dict) and read.get("outcome") == OUTCOME_DISCHARGED:
            _close_discharged_group(conn, subject, run_id)
        return _write_status(conn, read)


def _close_discharged_group(conn: Any, subject: Mapping[str, Any], run_id: str) -> None:
    """A plan group discharged by waivers is accepted, so it records who it answered."""
    if not (subject.get("shared_plan") or {}).get("group_id"):
        return
    from yoke_core.domain.deployment_qa_plan_groups import close_group
    from yoke_core.domain.deployment_runs_lock import lock_run

    lock_run(conn, str(run_id))
    close_group(conn, subject)
    conn.commit()


@presentation_operation
@run_presentation
def _read_settlement(conn: Any, *, run_id: str, **subject: Any) -> Any:
    return _settle_reads(conn, run_id=run_id, **subject)


def _settle_reads(
    conn: Any,
    *,
    subject: Mapping[str, Any],
    target: Mapping[str, Any],
    run_id: str,
    stage_name: str,
    member_item_id: int | None,
) -> Any:
    """An answer, or a passed subject owing its acceptance write."""
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
            shared_plan_id=(subject.get("shared_plan") or {}).get("plan_id"),
        )
    )
    reasons = failure_reasons(failures)
    if obligations_fully_discharged(
        conn,
        run_id=run_id,
        stage_name=stage_name,
        member_item_id=member_item_id,
        execution_target_digest=current_target_digest,
    ):
        # Discharge answers the obligation even after a completed failure;
        # the execution and its verdict remain historical evidence.
        return discharged()
    if execution is None:
        member_answer = member_post_deploy_answer(conn, subject)
        if member_answer.discharges_without_cases:
            # Recorded emptiness or a carried member's own-flow exemption.
            result = discharged()
            if member_answer.verdict == NOT_REQUIRED:
                result["reasons"] = list(member_answer.reasons)
            return result
        # Every case passed across stopped walks: settle on the newest one.
        execution = (
            None
            if reasons
            else stopped_case_execution(
                conn,
                run_id=run_id,
                stage_name=stage_name,
                member_item_id=member_item_id,
                execution_target_digest=current_target_digest,
            )
        )
    pending = missing_execution_blocker(
        conn, run_id, stage_name, member_item_id, current_target_digest
    )
    if pending:
        reasons.insert(0, pending[1])
    if (
        not reasons
        and execution is None
        and member_item_id is not None
        and member_cases_passed(
            conn, run_id, stage_name, member_item_id, current_target_digest
        )
    ):
        blockers = run_qa_blockers(conn, run_id, member_item_id, subject)
        return waiting(blockers) if blockers else discharged()
    if reasons:
        # A missing execution alongside red cases still reads as blocked: the
        # red verdicts are the reason no acceptable execution can exist, and
        # calling that "waiting" is the collapse this split undoes.
        return _with_pin_diagnosis(conn, run_id, settled(reasons, failures))
    if execution is None:
        return waiting([f"Run `yoke watch deploy -- {run_id}`"])
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
    return Acceptance(subject, target, run_id, execution)


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
