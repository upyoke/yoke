"""Screenshot-evidence handlers — qa.screenshot_evidence.{pending_count,satisfy}.

The advance browser-QA gate's evidence legs (family docstring:
:mod:`yoke_core.domain.handlers.qa_browser`):

- ``qa.screenshot_evidence.pending_count`` — read: how many unwaived
  ``ac_verification`` requirements carrying the
  ``requires_screenshot_evidence`` token still lack a passing
  ``browser_substrate`` run. The gate hard-blocks on a positive count when
  a scenario produced no screenshots.
- ``qa.screenshot_evidence.satisfy`` — write: bridge an
  inspection-verified browser capture into ``ac_verification`` passes,
  mirroring
  :func:`yoke_core.domain.qa_evidence_bridge.cmd_satisfy_screenshot_evidence`
  without the CLI ``sys.exit`` branches (the exit-3 capture guard becomes
  the typed ``capture_not_verified`` error).
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel

from yoke_core.domain.handlers.qa import _error, _p
from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    HandlerOutcome,
)

# Deliberate case-sensitive match against the internal success_policy token
# (same predicate as qa_evidence_bridge).
_UNSATISFIED_SQL = """
    SELECT r.id FROM qa_requirements r
    WHERE r.item_id = {p}
      AND r.qa_kind = 'ac_verification'
      AND r.success_policy LIKE '%%requires_screenshot_evidence%%'
      AND r.waived_at IS NULL
      AND r.id NOT IN (
        SELECT qa_requirement_id FROM qa_runs
        WHERE verdict = 'pass' AND executor_type = 'browser_substrate'
      )
    ORDER BY r.id
"""

DEFAULT_EVIDENCE = (
    "Browser QA screenshot evaluation passed -- screenshots consistent "
    "with acceptance criteria"
)


class QaScreenshotEvidencePendingCountRequest(BaseModel):
    pass


class QaScreenshotEvidencePendingCountResponse(BaseModel):
    item_id: int
    pending_count: int


def handle_qa_screenshot_evidence_pending_count(
    request: FunctionCallRequest,
) -> HandlerOutcome:
    from yoke_core.domain.db_helpers import connect, query_rows

    item_id = request.target.item_id
    if item_id is None:
        return _error(
            "target_invalid",
            "qa.screenshot_evidence.pending_count requires target.item_id",
        )
    conn = connect()
    try:
        rows = query_rows(
            conn, _UNSATISFIED_SQL.format(p=_p(conn)), (int(item_id),),
        )
    finally:
        conn.close()
    return HandlerOutcome(
        result_payload={
            "item_id": int(item_id), "pending_count": len(rows),
        },
        primary_success=True,
    )


class QaScreenshotEvidenceSatisfyRequest(BaseModel):
    evidence: Optional[str] = None


class QaScreenshotEvidenceSatisfyResponse(BaseModel):
    item_id: int
    satisfied_count: int


def handle_qa_screenshot_evidence_satisfy(
    request: FunctionCallRequest,
) -> HandlerOutcome:
    from yoke_core.domain.db_helpers import (
        connect,
        iso8601_now,
        query_rows,
        query_scalar,
    )

    item_id = request.target.item_id
    if item_id is None:
        return _error(
            "target_invalid",
            "qa.screenshot_evidence.satisfy requires target.item_id",
        )
    payload = request.payload or {}
    evidence = payload.get("evidence") or DEFAULT_EVIDENCE

    conn = connect()
    try:
        p = _p(conn)
        # Guard: require an inspection-verified capture before bridging.
        inspected_count = query_scalar(conn, f"""
            SELECT COUNT(*) FROM qa_runs qr
            JOIN qa_requirements r ON r.id = qr.qa_requirement_id
            WHERE r.item_id = {p}
              AND r.qa_kind IN ('browser_smoke','browser_diff')
              AND qr.executor_type = 'browser_substrate'
              AND qr.execution_status = 'captured'
              AND qr.verdict = 'pass'
        """, (int(item_id),))
        if not inspected_count or int(inspected_count) == 0:
            return _error(
                "capture_not_verified",
                f"item {item_id} has no inspection-verified browser captures "
                "(need execution_status='captured' AND verdict='pass' on a "
                "browser_smoke/browser_diff run). Call qa.run.complete with "
                "verdict='pass' on the capture run after screenshot "
                "inspection, then retry.",
            )

        unsatisfied = query_rows(
            conn, _UNSATISFIED_SQL.format(p=p), (int(item_id),),
        )
        if not unsatisfied:
            return HandlerOutcome(
                result_payload={
                    "item_id": int(item_id), "satisfied_count": 0,
                },
                primary_success=True,
            )

        now_iso = iso8601_now()
        for req_row in unsatisfied:
            conn.execute(
                f"""INSERT INTO qa_runs
                    (qa_requirement_id, executor_type, qa_kind, verdict,
                     raw_result, started_at, completed_at, created_at)
                    VALUES ({p}, 'browser_substrate', 'ac_verification',
                            'pass', {p}, {p}, {p}, {p})""",
                (int(req_row["id"]), evidence, now_iso, now_iso, now_iso),
            )
        conn.commit()

        count = query_scalar(conn, f"""
            SELECT COUNT(*) FROM qa_requirements r
            WHERE r.item_id = {p}
              AND r.qa_kind = 'ac_verification'
              AND r.success_policy LIKE '%%requires_screenshot_evidence%%'
              AND r.waived_at IS NULL
              AND r.id IN (
                SELECT qa_requirement_id FROM qa_runs
                WHERE verdict = 'pass' AND executor_type = 'browser_substrate'
              )
        """, (int(item_id),))
    finally:
        conn.close()

    return HandlerOutcome(
        result_payload={
            "item_id": int(item_id), "satisfied_count": int(count or 0),
        },
        primary_success=True,
    )


__all__ = [
    "DEFAULT_EVIDENCE",
    "QaScreenshotEvidencePendingCountRequest",
    "QaScreenshotEvidencePendingCountResponse",
    "QaScreenshotEvidenceSatisfyRequest",
    "QaScreenshotEvidenceSatisfyResponse",
    "handle_qa_screenshot_evidence_pending_count",
    "handle_qa_screenshot_evidence_satisfy",
]
