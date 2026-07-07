"""QA run-record handler — `qa.run.record_verdict.run`.

Records a verdict against an existing qa_requirement by inserting a new row
into ``qa_runs`` and emitting ``QARunCompleted`` through
:func:`yoke_core.domain.qa_events.emit_qa_run_event`. Mirrors the gates
in :func:`yoke_core.domain.qa_execution.cmd_run_add` without the CLI
sys.exit branches.

``claim_required_kind="item"`` — the active claim is on the target item;
the qa_requirement row resolves to that item via its item_id (or
epic_id+task_num for epic-attached requirements).
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel

from yoke_core.domain import db_backend
from yoke_core.domain.handlers.qa import _error
from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    HandlerOutcome,
)


def _p(conn) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


class QaRunRecordVerdictRequest(BaseModel):
    executor_type: str
    verdict: str
    raw_result: Optional[str] = None
    duration_ms: Optional[int] = None


class QaRunRecordVerdictResponse(BaseModel):
    qa_run_id: int
    requirement_id: int
    verdict: str


def handle_qa_run_record_verdict(request: FunctionCallRequest) -> HandlerOutcome:
    from yoke_core.domain.db_helpers import connect, iso8601_now, query_one
    from yoke_core.domain import qa_events
    from yoke_core.domain.qa_constants import (
        VALID_BROWSER_QA_KINDS,
        VALID_VERDICTS,
    )

    target = request.target
    req_id = target.qa_requirement_id
    if req_id is None:
        return _error(
            "target_invalid",
            "qa.run.record_verdict requires target.qa_requirement_id",
        )
    payload = request.payload or {}
    executor_type = payload.get("executor_type")
    verdict = payload.get("verdict")
    raw_result = payload.get("raw_result")
    duration_ms = payload.get("duration_ms")
    if not isinstance(executor_type, str) or not executor_type:
        return _error(
            "payload_invalid", "executor_type is required",
            jsonpath="$.payload.executor_type",
        )
    if verdict not in VALID_VERDICTS:
        return _error(
            "payload_invalid",
            f"verdict must be one of {list(VALID_VERDICTS)}",
            jsonpath="$.payload.verdict",
        )

    conn = connect()
    try:
        p = _p(conn)
        row = query_one(
            conn,
            f"SELECT qa_kind FROM qa_requirements WHERE id = {p}",
            (int(req_id),),
        )
        if row is None:
            return _error("not_found", f"requirement {req_id} not found")
        qa_kind = str(row["qa_kind"])
        if executor_type == "agent" and qa_kind in VALID_BROWSER_QA_KINDS:
            return _error(
                "policy_violation",
                f"executor_type 'agent' is not allowed for qa_kind {qa_kind!r} "
                f"-- use browser_substrate",
                jsonpath="$.payload.executor_type",
            )

        now_iso = iso8601_now()
        p = _p(conn)
        cur = conn.execute(
            "INSERT INTO qa_runs "
            "(qa_requirement_id, executor_type, qa_kind, verdict, raw_result, "
            "duration_ms, started_at, completed_at, created_at) "
            f"VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}) "
            "RETURNING id",
            (
                int(req_id), executor_type, qa_kind, verdict, raw_result,
                duration_ms, now_iso, now_iso, now_iso,
            ),
        )
        run_id = int(cur.fetchone()[0])
        conn.commit()
        qa_events.emit_qa_run_event(
            conn,
            db_path=None,
            event_name="QARunCompleted",
            run_id=run_id,
            requirement_id=int(req_id),
            qa_kind=qa_kind,
            verdict=str(verdict),
        )
    finally:
        conn.close()

    return HandlerOutcome(
        result_payload={
            "qa_run_id": run_id,
            "requirement_id": int(req_id),
            "verdict": str(verdict),
        },
        primary_success=True,
    )


__all__ = [
    "QaRunRecordVerdictRequest", "QaRunRecordVerdictResponse",
    "handle_qa_run_record_verdict",
]
