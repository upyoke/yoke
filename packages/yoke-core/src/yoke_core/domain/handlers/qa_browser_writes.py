"""Browser-QA write handlers — qa.run.add, qa.run.complete, qa.artifact.add."""

from __future__ import annotations

from yoke_contracts.api.function_call import FunctionCallRequest, HandlerOutcome
from yoke_contracts.qa_execution_status import execution_status_error
from yoke_core.domain import qa_events
from yoke_core.domain import qa_undetermined_evidence as _review_evidence
from yoke_core.domain.db_helpers import connect, utc_now, query_one
from yoke_core.domain.handlers.qa import _error, _p
from yoke_core.domain.handlers.qa_artifact_add import handle_qa_artifact_add
from yoke_core.domain.handlers.qa_browser_write_models import (
    QaArtifactAddRequest,
    QaArtifactAddResponse,
    QaRunAddRequest,
    QaRunAddResponse,
    QaRunCompleteRequest,
    QaRunCompleteResponse,
)
from yoke_core.domain.qa_capture_agreement import (
    CAPTURE_STATUS_ARTIFACT_DISAGREEMENT,
    captured_without_evidence_error,
    run_artifact_count,
)
from yoke_core.domain.qa_pending_agent_review import pending_review_verdict_refusal
from yoke_core.domain.qa_run_verdict_record import insert_qa_run, update_qa_run
from yoke_core.domain.qa_constants import (
    NEEDS_REVIEW_OUTCOME,
    VALID_VERDICTS,
    case_outcome_for_verdict,
    is_agent_reviewed_case,
    is_browser_method_requirement,
    normalized_verdict_reason,
)


def handle_qa_run_add(request: FunctionCallRequest) -> HandlerOutcome:

    req_id = request.target.qa_requirement_id
    if req_id is None:
        return _error(
            "target_invalid",
            "qa.run.add requires target.qa_requirement_id",
        )
    payload = request.payload or {}
    performed_by = payload.get("performed_by")
    qa_kind = payload.get("qa_kind")
    verdict = payload.get("verdict")
    verdict_reason = payload.get("verdict_reason")
    execution_status = payload.get("execution_status")
    capture_degraded_reason = payload.get("capture_degraded_reason")
    raw_result = payload.get("raw_result")
    duration_ms = payload.get("duration_ms")
    if not isinstance(performed_by, str) or not performed_by:
        return _error(
            "payload_invalid",
            "performed_by is required",
            jsonpath="$.payload.performed_by",
        )
    if verdict is not None and verdict not in VALID_VERDICTS:
        return _error(
            "payload_invalid", "invalid verdict", jsonpath="$.payload.verdict"
        )
    try:
        verdict_reason = normalized_verdict_reason(verdict, verdict_reason)
    except ValueError as exc:
        return _error("payload_invalid", str(exc), jsonpath="$.payload.verdict_reason")
    if status_issue := execution_status_error(execution_status):
        return _error(
            "payload_invalid", status_issue, jsonpath="$.payload.execution_status"
        )
    conn = connect()
    try:
        p = _p(conn)
        row = query_one(
            conn,
            f"SELECT qa_kind, method_id, verdict_path, blocking_mode, waived_at, item_id, "
            f"method_config, runner_id FROM qa_requirements WHERE id = {p}",
            (int(req_id),),
        )
        if row is None:
            return _error("not_found", f"requirement {req_id} not found")
        stored_kind = str(row["qa_kind"])
        if qa_kind is not None and qa_kind != stored_kind:
            return _error(
                "payload_invalid",
                f"qa_kind {qa_kind!r} does not match the requirement's "
                f"stored kind {stored_kind!r}",
                jsonpath="$.payload.qa_kind",
            )
        if performed_by == "agent" and is_browser_method_requirement(row["method_id"]):
            return _error(
                "policy_violation",
                "performed_by 'agent' is not allowed for Browser methods "
                "-- use browser_substrate",
                jsonpath="$.payload.performed_by",
            )
        if issue := _review_evidence.agent_undetermined_evidence_error(
            conn, performed_by=performed_by, verdict=verdict
        ) or pending_review_verdict_refusal(conn, int(req_id), verdict, row):
            code = getattr(issue, "code", "policy_violation")
            return _error(code, str(issue), jsonpath="$.payload.verdict")
        from yoke_core.domain.qa_run_commit_binding import bind_recorded_raw_result

        raw_result, bind_error = bind_recorded_raw_result(
            verdict=verdict,
            raw_result=raw_result,
            performed_by=performed_by,
            blocking_mode=row["blocking_mode"],
            waived_at=row["waived_at"],
            head_sha=payload.get("head_sha"),
            item_id=row["item_id"],
            conn=conn,
            requirement=dict(row),
        )
        if bind_error:
            return _error(
                "payload_invalid", bind_error, jsonpath="$.payload.raw_result"
            )
        if issue := captured_without_evidence_error(
            execution_status=execution_status,
            artifact_count=0,
            capture_degraded_reason=capture_degraded_reason,
        ):
            return _error(
                CAPTURE_STATUS_ARTIFACT_DISAGREEMENT,
                issue,
                jsonpath="$.payload.execution_status",
            )
        from yoke_core.domain.qa_requirement_pass_currency import (
            stamp_executed_method_config,
        )

        raw_result = stamp_executed_method_config(
            raw_result, row.get("method_config"), conn=conn, requirement_id=int(req_id)
        )
        now = utc_now()
        completed_at_value = (
            now if (verdict is not None or execution_status is not None) else None
        )
        agent_case = is_agent_reviewed_case(row["verdict_path"], row["method_id"])
        if execution_status == "captured" and agent_case:
            case_outcome_val = NEEDS_REVIEW_OUTCOME
        elif verdict is not None:
            case_outcome_val = case_outcome_for_verdict(verdict)
        else:
            case_outcome_val = None

        run_id = insert_qa_run(
            conn,
            qa_requirement_id=int(req_id),
            performed_by=performed_by,
            qa_kind=stored_kind,
            verdict=verdict,
            verdict_reason=verdict_reason,
            execution_status=execution_status,
            case_outcome=case_outcome_val,
            capture_degraded_reason=capture_degraded_reason,
            raw_result=raw_result,
            duration_ms=duration_ms,
            started_at=now,
            completed_at=completed_at_value,
            created_at=now,
        ).run_id
        conn.commit()
        event_name = (
            "QARunCompleted"
            if verdict is not None
            else ("QARunCaptured" if execution_status is not None else "QARunStarted")
        )
        qa_events.emit_qa_run_event(
            conn,
            db_path=None,
            event_name=event_name,
            run_id=run_id,
            requirement_id=int(req_id),
            qa_kind=stored_kind,
            verdict=verdict,
            verdict_reason=verdict_reason,
        )
    finally:
        conn.close()
    return HandlerOutcome(
        result_payload={"qa_run_id": run_id, "requirement_id": int(req_id)},
        primary_success=True,
    )


def handle_qa_run_complete(request: FunctionCallRequest) -> HandlerOutcome:
    from yoke_core.domain import qa_events
    from yoke_core.domain.db_helpers import connect, utc_now, query_one
    from yoke_contracts.qa_execution_status import CAPTURED
    from yoke_core.domain.qa_constants import (
        NEEDS_REVIEW_OUTCOME,
        VALID_VERDICTS,
        case_outcome_for_verdict,
        is_agent_reviewed_case,
        normalized_verdict_reason,
    )

    req_id = request.target.qa_requirement_id
    if req_id is None:
        return _error(
            "target_invalid",
            "qa.run.complete requires target.qa_requirement_id",
        )
    payload = request.payload or {}
    run_id = payload.get("run_id")
    verdict = payload.get("verdict")
    verdict_reason = payload.get("verdict_reason")
    execution_status = payload.get("execution_status")
    capture_degraded_reason = payload.get("capture_degraded_reason")
    raw_result = payload.get("raw_result")
    duration_ms = payload.get("duration_ms")
    if not isinstance(run_id, int):
        return _error(
            "payload_invalid", "run_id is required", jsonpath="$.payload.run_id"
        )
    if verdict is None and execution_status is None:
        return _error(
            "payload_invalid",
            "at least one of verdict or execution_status is required",
            jsonpath="$.payload.verdict",
        )
    if verdict is not None and verdict not in VALID_VERDICTS:
        return _error(
            "payload_invalid", "invalid verdict", jsonpath="$.payload.verdict"
        )
    try:
        verdict_reason = normalized_verdict_reason(verdict, verdict_reason)
    except ValueError as exc:
        return _error("payload_invalid", str(exc), jsonpath="$.payload.verdict_reason")
    if status_issue := execution_status_error(execution_status):
        return _error(
            "payload_invalid", status_issue, jsonpath="$.payload.execution_status"
        )
    conn = connect()
    try:
        p = _p(conn)
        row = query_one(
            conn,
            "SELECT run.qa_requirement_id, run.qa_kind, run.performed_by, "
            "run.raw_result, run.capture_degraded_reason, req.verdict_path, "
            "req.method_id FROM qa_runs run "
            "JOIN qa_requirements req ON req.id = run.qa_requirement_id "
            f"WHERE run.id = {p}",
            (int(run_id),),
        )
        if row is None:
            return _error("not_found", f"run {run_id} not found")
        if int(row["qa_requirement_id"]) != int(req_id):
            return _error(
                "target_invalid",
                f"run {run_id} belongs to requirement "
                f"{row['qa_requirement_id']}, not {req_id}",
            )
        if issue := _review_evidence.agent_undetermined_evidence_error(
            conn,
            performed_by=str(row["performed_by"]),
            verdict=verdict,
            run_ids=(int(run_id),),
        ) or pending_review_verdict_refusal(conn, int(req_id), verdict, row):
            code = getattr(issue, "code", "policy_violation")
            return _error(code, str(issue), jsonpath="$.payload.verdict")
        reason = capture_degraded_reason
        if reason is None:
            reason = row["capture_degraded_reason"]
        if issue := captured_without_evidence_error(
            execution_status=execution_status,
            artifact_count=run_artifact_count(conn, int(run_id)),
            capture_degraded_reason=reason,
        ):
            return _error(
                CAPTURE_STATUS_ARTIFACT_DISAGREEMENT,
                issue,
                jsonpath="$.payload.execution_status",
            )
        columns: dict = {"completed_at": utc_now()}
        if verdict is not None:
            columns.update(
                verdict=verdict,
                verdict_reason=verdict_reason,
                case_outcome=case_outcome_for_verdict(verdict),
            )
        elif execution_status == CAPTURED and is_agent_reviewed_case(
            row["verdict_path"], row["method_id"]
        ):
            columns["case_outcome"] = NEEDS_REVIEW_OUTCOME
        if execution_status is not None:
            columns["execution_status"] = execution_status
        if capture_degraded_reason is not None:
            columns["capture_degraded_reason"] = capture_degraded_reason
        if raw_result is not None:
            from yoke_core.domain.qa_requirement_pass_currency import (
                retain_start_bound_method_config,
            )

            columns["raw_result"] = retain_start_bound_method_config(
                row["raw_result"], raw_result
            )
        if duration_ms is not None:
            columns["duration_ms"] = duration_ms
        update_qa_run(conn, int(run_id), columns)
        conn.commit()
        event_name = "QARunCompleted" if verdict is not None else "QARunCaptured"
        qa_events.emit_qa_run_event(
            conn,
            db_path=None,
            event_name=event_name,
            run_id=int(run_id),
            requirement_id=int(req_id),
            qa_kind=str(row["qa_kind"]),
            verdict=verdict,
            verdict_reason=verdict_reason,
        )
    finally:
        conn.close()
    return HandlerOutcome(
        result_payload={"qa_run_id": int(run_id)},
        primary_success=True,
    )


__all__ = [
    "QaRunAddRequest",
    "QaRunAddResponse",
    "QaRunCompleteRequest",
    "QaRunCompleteResponse",
    "QaArtifactAddRequest",
    "QaArtifactAddResponse",
    "handle_qa_run_add",
    "handle_qa_run_complete",
    "handle_qa_artifact_add",
]
