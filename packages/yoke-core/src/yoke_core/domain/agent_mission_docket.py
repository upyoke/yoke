"""Persist a mission preparation docket before dispatching its walker."""

from __future__ import annotations

from typing import Any

from yoke_contracts.timestamps import utc_now


def insert_mission_docket(
    conn: Any,
    *,
    execution: dict[str, Any],
    case: dict[str, Any],
    preparation: dict[str, Any],
    lease_id: int | None,
    contract_digest: str,
) -> tuple[int, dict[str, Any]]:
    from yoke_core.domain.machine_qa_execution_protocol import (
        host_control_submission_receipt,
    )
    from yoke_core.domain.probe_reply_rejection_evidence import (
        record_reply_rejections,
        rejection_verdict_reason,
        reply_rejections,
    )
    from yoke_core.domain.qa_capture_agreement import AGENT_MISSION_DOCKET_REASON
    from yoke_core.domain.qa_plan_execution_store import canonical
    from yoke_core.domain.qa_requirement_pass_currency import (
        stamp_executed_method_config,
    )

    now = utc_now()
    executor = str(case["method_config"]["executor"])
    transcript = {
        "executor": executor,
        "preparation": preparation,
        "plan_execution_id": str(execution["id"]),
        "lease_id": lease_id,
    }
    if lease_id is not None:
        transcript["host_control_submission"] = host_control_submission_receipt(
            lease_id,
            contract_digest,
            reset_owed_baseline=case.get("reset_owed_baseline"),
        )
    from yoke_core.domain.qa_run_verdict_record import insert_qa_run

    failed = not preparation["ok"]
    failure = preparation["evidence"].get("preparation_failure", {})
    rejections = reply_rejections(preparation["evidence"])
    reason = " | ".join(
        part
        for part in (rejection_verdict_reason(rejections), failure.get("diagnostic"))
        if part
    )
    run_id = insert_qa_run(
        conn,
        qa_requirement_id=int(case["requirement_id"]),
        performed_by="agent_mission",
        qa_kind=str(case["qa_kind"]),
        execution_status="capture_failed" if failed else "captured",
        case_outcome="blocked_on_precondition" if failed else "needs_review",
        verdict="error" if failed else None,
        verdict_reason=(reason or None) if failed else None,
        capture_degraded_reason=preparation.get("error_code")
        if failed
        else AGENT_MISSION_DOCKET_REASON,
        raw_result=stamp_executed_method_config(
            canonical(transcript),
            case.get("method_config"),
            execution_target_digest=case.get("execution_target_digest"),
        ),
        started_at=now,
        completed_at=now,
        created_at=now,
    ).run_id
    record_reply_rejections(
        conn,
        requirement_id=int(case["requirement_id"]),
        run_id=run_id,
        rejections=rejections,
        metadata={"executor": executor, "baseline": preparation.get("baseline")},
        created_at=now,
    )
    result = {
        "requirement_id": int(case["requirement_id"]),
        "runner_id": "agent_mission",
        "run_id": run_id,
        "verdict": "error" if failed else None,
        "case_outcome": "blocked_on_precondition" if failed else "needs_review",
        "executor": executor,
        "preparation": preparation,
    }
    if failed:
        result.update(
            error_code=preparation.get("error_code"),
            error=reason or None,
            recovery=failure.get("recovery"),
        )
    return run_id, result
