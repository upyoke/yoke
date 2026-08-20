"""QA run-record handler — `qa.run.record_verdict.run`.

Records a verdict against an existing qa_requirement by inserting a new row
into ``qa_runs`` and emitting ``QARunCompleted`` through
:func:`yoke_core.domain.qa_events.emit_qa_run_event`. Mirrors the gates
in :func:`yoke_core.domain.qa_execution.cmd_run_add` without the CLI
sys.exit branches.

``claim_required_kind="qa_subject"`` resolves an item-backed requirement to
its active item claim and permits a deployment-run-backed requirement through
the run's project authorization.
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


def _names_no_verified_tree(verdict, requirement_row, raw_result) -> bool:
    """Whether a run the terminal gate will SHA-match names no tree.

    The gate matches every passing blocking run against the merged tree, so a
    run recorded without one is unusable there however it reads here.
    """
    from yoke_core.domain.qa_merging_identity import recorded_head_sha

    if str(verdict or "").strip().lower() != "pass":
        return False
    if str(requirement_row["blocking_mode"] or "") != "blocking":
        return False
    if requirement_row["waived_at"]:
        return False
    return not recorded_head_sha(raw_result)


class QaRunRecordVerdictRequest(BaseModel):
    performed_by: str
    verdict: str
    verdict_reason: Optional[str] = None
    raw_result: Optional[str] = None
    duration_ms: Optional[int] = None


class QaRunRecordVerdictResponse(BaseModel):
    qa_run_id: int
    requirement_id: int
    verdict: str
    verdict_reason: Optional[str] = None


def handle_qa_run_record_verdict(request: FunctionCallRequest) -> HandlerOutcome:
    from yoke_core.domain.db_helpers import connect, iso8601_now, query_one
    from yoke_core.domain import qa_events
    from yoke_core.domain.qa_constants import (
        VALID_VERDICTS,
        case_outcome_for_verdict,
        is_browser_method_requirement,
        normalized_verdict_reason,
    )

    target = request.target
    req_id = target.qa_requirement_id
    if req_id is None:
        return _error(
            "target_invalid",
            "qa.run.record_verdict requires target.qa_requirement_id",
        )
    payload = request.payload or {}
    performed_by = payload.get("performed_by")
    verdict = payload.get("verdict")
    verdict_reason = payload.get("verdict_reason")
    raw_result = payload.get("raw_result")
    duration_ms = payload.get("duration_ms")
    if not isinstance(performed_by, str) or not performed_by:
        return _error(
            "payload_invalid",
            "performed_by is required",
            jsonpath="$.payload.performed_by",
        )
    if verdict not in VALID_VERDICTS:
        return _error(
            "payload_invalid",
            f"verdict must be one of {list(VALID_VERDICTS)}",
            jsonpath="$.payload.verdict",
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
            "SELECT qa_kind, method_id, blocking_mode, waived_at "
            f"FROM qa_requirements WHERE id = {p}",
            (int(req_id),),
        )
        if row is None:
            return _error("not_found", f"requirement {req_id} not found")
        qa_kind = str(row["qa_kind"])
        if performed_by == "agent" and is_browser_method_requirement(row["method_id"]):
            return _error(
                "policy_violation",
                "performed_by 'agent' is not allowed for Browser methods "
                "-- use browser_substrate",
                jsonpath="$.payload.performed_by",
            )

        if _names_no_verified_tree(verdict, row, raw_result):
            return _error(
                "payload_invalid",
                "a passing verdict on a blocking requirement must name the "
                "tree it verified: pass --raw-result as JSON carrying "
                '{"verification_tree": {"head_sha": "<commit>"}}. Recorded '
                "without it, the terminal gate reads the run as <missing> and "
                "refuses the merge even though this write and "
                "`yoke qa gate-summary` both report the requirement satisfied.",
                jsonpath="$.payload.raw_result",
            )

        now_iso = iso8601_now()
        p = _p(conn)
        cur = conn.execute(
            "INSERT INTO qa_runs "
            "(qa_requirement_id, performed_by, qa_kind, verdict, verdict_reason, "
            "case_outcome, raw_result, duration_ms, started_at, "
            "completed_at, created_at) "
            f"VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}) "
            "RETURNING id",
            (
                int(req_id),
                performed_by,
                qa_kind,
                verdict,
                verdict_reason,
                case_outcome_for_verdict(verdict),
                raw_result,
                duration_ms,
                now_iso,
                now_iso,
                now_iso,
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
            verdict_reason=verdict_reason,
        )
    finally:
        conn.close()

    return HandlerOutcome(
        result_payload={
            "qa_run_id": run_id,
            "requirement_id": int(req_id),
            "verdict": str(verdict),
            "verdict_reason": verdict_reason,
        },
        primary_success=True,
    )


__all__ = [
    "QaRunRecordVerdictRequest",
    "QaRunRecordVerdictResponse",
    "handle_qa_run_record_verdict",
]
