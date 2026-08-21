"""Browser-QA write handlers — qa.run.add, qa.run.complete, qa.artifact.add."""

from __future__ import annotations

from yoke_contracts.api.function_call import FunctionCallRequest, HandlerOutcome
from yoke_core.domain.handlers.qa import _error, _p
from yoke_core.domain.handlers.qa_browser_write_models import (
    QaArtifactAddRequest,
    QaArtifactAddResponse,
    QaRunAddRequest,
    QaRunAddResponse,
    QaRunCompleteRequest,
    QaRunCompleteResponse,
)


def handle_qa_run_add(request: FunctionCallRequest) -> HandlerOutcome:
    from yoke_core.domain import qa_events
    from yoke_core.domain.db_helpers import connect, iso8601_now, query_one
    from yoke_core.domain.qa_constants import (
        VALID_VERDICTS,
        case_outcome_for_verdict,
        is_browser_method_requirement,
        normalized_verdict_reason,
    )

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

    conn = connect()
    try:
        p = _p(conn)
        row = query_one(
            conn,
            f"SELECT qa_kind, method_id, blocking_mode, waived_at, item_id "
            f"FROM qa_requirements WHERE id = {p}",
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

        from yoke_core.domain.qa_run_commit_binding import bind_recorded_raw_result
        raw_result, bind_error = bind_recorded_raw_result(
            verdict=verdict, raw_result=raw_result, performed_by=performed_by,
            blocking_mode=row["blocking_mode"], waived_at=row["waived_at"],
            head_sha=payload.get("head_sha"), item_id=row["item_id"], conn=conn,
        )
        if bind_error:
            return _error(
                "payload_invalid", bind_error, jsonpath="$.payload.raw_result",
            )
        now_iso = iso8601_now()
        completed_at_value = (
            now_iso if (verdict is not None or execution_status is not None) else None
        )
        cur = conn.execute(
            "INSERT INTO qa_runs "
            "(qa_requirement_id, performed_by, qa_kind, verdict, verdict_reason, "
            "execution_status, case_outcome, raw_result, duration_ms, "
            "started_at, completed_at, created_at) "
            f"VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}) "
            "RETURNING id",
            (
                int(req_id),
                performed_by,
                stored_kind,
                verdict,
                verdict_reason,
                execution_status,
                case_outcome_for_verdict(verdict),
                raw_result,
                duration_ms,
                now_iso,
                completed_at_value,
                now_iso,
            ),
        )
        run_id = int(cur.fetchone()[0])
        conn.commit()
        if verdict is not None:
            event_name = "QARunCompleted"
        elif execution_status is not None:
            event_name = "QARunCaptured"
        else:
            event_name = "QARunStarted"
        qa_events.emit_qa_run_event(
            conn,
            db_path=None,
            event_name=event_name,
            run_id=run_id,
            requirement_id=int(req_id),
            qa_kind=stored_kind,
            verdict=verdict, verdict_reason=verdict_reason,
        )
    finally:
        conn.close()

    return HandlerOutcome(
        result_payload={"qa_run_id": run_id, "requirement_id": int(req_id)},
        primary_success=True,
    )


def handle_qa_run_complete(request: FunctionCallRequest) -> HandlerOutcome:
    from yoke_core.domain import qa_events
    from yoke_core.domain.db_helpers import connect, iso8601_now, query_one
    from yoke_core.domain.qa_constants import (
        VALID_VERDICTS,
        case_outcome_for_verdict,
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
    raw_result = payload.get("raw_result")
    duration_ms = payload.get("duration_ms")
    if not isinstance(run_id, int):
        return _error(
            "payload_invalid",
            "run_id is required",
            jsonpath="$.payload.run_id",
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

    conn = connect()
    try:
        p = _p(conn)
        row = query_one(
            conn,
            f"SELECT qa_requirement_id, qa_kind FROM qa_runs WHERE id = {p}",
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

        params: list = [iso8601_now()]
        set_parts = [f"completed_at = {p}"]
        if verdict is not None:
            set_parts.append(f"verdict = {p}")
            params.append(verdict)
            set_parts.append(f"verdict_reason = {p}")
            params.append(verdict_reason)
            set_parts.append(f"case_outcome = {p}")
            params.append(case_outcome_for_verdict(verdict))
        if execution_status is not None:
            set_parts.append(f"execution_status = {p}")
            params.append(execution_status)
        if raw_result is not None:
            set_parts.append(f"raw_result = {p}")
            params.append(raw_result)
        if duration_ms is not None:
            set_parts.append(f"duration_ms = {p}")
            params.append(duration_ms)
        params.append(int(run_id))
        conn.execute(
            f"UPDATE qa_runs SET {', '.join(set_parts)} WHERE id = {p}",
            tuple(params),
        )
        conn.commit()
        event_name = "QARunCompleted" if verdict is not None else "QARunCaptured"
        qa_events.emit_qa_run_event(
            conn,
            db_path=None,
            event_name=event_name,
            run_id=int(run_id),
            requirement_id=int(req_id),
            qa_kind=str(row["qa_kind"]),
            verdict=verdict, verdict_reason=verdict_reason,
        )
    finally:
        conn.close()

    return HandlerOutcome(
        result_payload={"qa_run_id": int(run_id)},
        primary_success=True,
    )


def handle_qa_artifact_add(request: FunctionCallRequest) -> HandlerOutcome:
    from yoke_core.domain.db_helpers import connect, iso8601_now
    from yoke_core.domain.qa_artifact_handle import (
        ArtifactHandleError,
        parse_handle,
        serialize_handle,
    )
    from yoke_core.domain.qa_artifact_ops import (
        BARE_PATH_GUIDANCE,
        QaArtifactLimitError,
        ensure_artifact_capacity,
    )

    req_id = request.target.qa_requirement_id
    if req_id is None:
        return _error(
            "target_invalid",
            "qa.artifact.add requires target.qa_requirement_id",
        )
    payload = request.payload or {}
    run_id = payload.get("run_id")
    artifact_type = payload.get("artifact_type")
    content_type = payload.get("content_type")
    metadata = payload.get("metadata")
    if not isinstance(run_id, int):
        return _error(
            "payload_invalid",
            "run_id is required",
            jsonpath="$.payload.run_id",
        )
    if not isinstance(artifact_type, str) or not artifact_type:
        return _error(
            "payload_invalid",
            "artifact_type is required",
            jsonpath="$.payload.artifact_type",
        )
    if "storage_path" in payload:
        return _error(
            "payload_invalid",
            f"storage_path is retired; {BARE_PATH_GUIDANCE}",
            jsonpath="$.payload.storage_path",
        )
    try:
        handle_text = serialize_handle(parse_handle(payload.get("artifact_handle")))
    except ArtifactHandleError as exc:
        return _error(
            "payload_invalid",
            f"{exc}. {BARE_PATH_GUIDANCE}",
            jsonpath="$.payload.artifact_handle",
        )
    conn = connect()
    try:
        p = _p(conn)
        try:
            stored_requirement_id = ensure_artifact_capacity(conn, run_id)
        except QaArtifactLimitError as exc:
            return _error("policy_violation", str(exc))
        if stored_requirement_id is None:
            return _error("not_found", f"run {run_id} not found")
        if stored_requirement_id != int(req_id):
            return _error(
                "target_invalid",
                f"run {run_id} belongs to requirement "
                f"{stored_requirement_id}, not {req_id}",
            )
        cur = conn.execute(
            "INSERT INTO qa_artifacts "
            "(qa_run_id, artifact_type, content_type, artifact_handle, "
            "metadata, created_at) "
            f"VALUES ({p}, {p}, {p}, {p}, {p}, {p}) RETURNING id",
            (
                int(run_id),
                artifact_type,
                content_type,
                handle_text,
                metadata,
                iso8601_now(),
            ),
        )
        artifact_id = int(cur.fetchone()[0])
        conn.commit()
    finally:
        conn.close()

    return HandlerOutcome(
        result_payload={"qa_artifact_id": artifact_id},
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
