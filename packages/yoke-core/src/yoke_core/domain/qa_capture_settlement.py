"""Settle captured QA runs that a terminal plan execution would freeze."""

from __future__ import annotations

from typing import Any, Mapping

from yoke_core.domain.db_helpers import iso8601_now
from yoke_core.domain.qa_constants import case_outcome_for_verdict
from yoke_core.domain.qa_plan_execution_store import marker
from yoke_core.domain.qa_run_verdict_record import (
    QaRunWrite,
    insert_qa_run,
    update_qa_run,
)
from yoke_core.domain.schema_common import _table_exists


CAPTURE_RUNNERS = ("browser_substrate", "host_control", "agent_mission")
INFLIGHT_CASE_FAILURE_VERDICT = "error"
UNREVIEWED_CAPTURE_VERDICT = "error"
UNREVIEWED_CAPTURE_REASON = (
    "execution ended without a review verdict; capture settled by execution termination"
)


def stamp_reviewed_capture(
    conn: Any,
    case: Mapping[str, Any],
    *,
    verdict: str,
    rationale: str,
    created_at: str,
) -> QaRunWrite:
    """Copy the reviewed verdict onto the capture without changing its shape.

    Browser-evidence gates match an agent-reviewed capture on
    execution_status='captured' plus case_outcome='needs_review' plus a
    linked passing review row. The first stamp is allowed; a replay no-ops
    because the immutability trigger only fires once a verdict exists.
    """
    p = marker(conn)
    capture = conn.execute(
        f"SELECT qa_requirement_id FROM qa_runs WHERE id={p}",
        (int(case["capture_run_id"]),),
    ).fetchone()
    if capture is None or int(capture[0]) != int(case["requirement_id"]):
        raise ValueError(
            "qa_review_capture_mismatch: capture does not belong to the reviewed "
            "requirement; rebuild the review bundle from the actual execution"
        )
    return update_qa_run(
        conn,
        int(case["capture_run_id"]),
        {"verdict": verdict, "verdict_reason": rationale},
        unjudged_only=True,
        default_completed_at=created_at,
    )


def settle_unreviewed_execution_captures(
    conn: Any,
    execution: Mapping[str, Any],
) -> None:
    """Settle still-NULL capture runs for this execution's requirements.

    Abort, error, and any other terminal path that never wrote a review
    would otherwise freeze those captures at every later item transition.
    """
    if not _table_exists(conn, "qa_runs"):
        return
    requirement_ids = sorted(
        {
            int(case["requirement_id"])
            for case in execution.get("roster") or []
            if case.get("requirement_id") is not None
        }
    )
    if not requirement_ids:
        return
    placeholder = marker(conn)
    runners = ", ".join(placeholder for _ in CAPTURE_RUNNERS)
    req_placeholders = ", ".join(placeholder for _ in requirement_ids)
    unjudged = conn.execute(
        f"SELECT id FROM qa_runs WHERE qa_requirement_id IN ({req_placeholders}) "
        f"AND performed_by IN ({runners}) AND verdict IS NULL ORDER BY id",
        (*requirement_ids, *CAPTURE_RUNNERS),
    ).fetchall()
    now = iso8601_now()
    for row in unjudged:
        update_qa_run(
            conn,
            int(row["id"] if hasattr(row, "keys") else row[0]),
            {
                "verdict": UNREVIEWED_CAPTURE_VERDICT,
                "verdict_reason": UNREVIEWED_CAPTURE_REASON,
            },
            unjudged_only=True,
            default_completed_at=now,
        )


def record_inflight_case_failure(
    conn: Any,
    execution: Mapping[str, Any],
    *,
    reason: str,
) -> None:
    """Record the failed run for the case a terminal execution left in flight.

    A case whose runner raised before recording anything leaves its
    requirement with no run of its own, and every latest-run projection
    reads that absence as "queued" — indistinguishable from a case nobody
    ever tried. The reasons below are the ones a client writes after its
    own case execution raised, so they are the evidence that this case WAS
    tried, and the plan reads failed instead of pending forever. An
    execution the stale sweep settled is deliberately excluded: nobody was
    driving it, so whether its first case had begun is unknown.
    """
    from yoke_core.domain.qa_plan_execution_abort_reason import (
        CASE_EXECUTION_ERROR_REASON,
        CONTINUATION_PRE_HOST_ERROR_REASON,
        abort_reason_code,
    )

    if abort_reason_code(reason) not in {
        CASE_EXECUTION_ERROR_REASON,
        CONTINUATION_PRE_HOST_ERROR_REASON,
    }:
        return
    if not _table_exists(conn, "qa_runs"):
        return
    roster = execution.get("roster") or []
    ordinal = int(execution["cursor_ordinal"])
    if ordinal >= len(roster):
        return
    case = roster[ordinal]
    requirement_id = case.get("requirement_id")
    if requirement_id is None:
        return
    placeholder = marker(conn)
    started_at = str(execution.get("created_at") or "")
    existing = conn.execute(
        f"SELECT id FROM qa_runs WHERE qa_requirement_id={placeholder} "
        f"AND created_at >= {placeholder} LIMIT 1",
        (int(requirement_id), started_at),
    ).fetchone()
    if existing is not None:
        return
    now = iso8601_now()
    insert_qa_run(
        conn,
        qa_requirement_id=int(requirement_id),
        performed_by=str(case.get("runner_id") or ""),
        qa_kind=str(case.get("qa_kind") or ""),
        verdict=INFLIGHT_CASE_FAILURE_VERDICT,
        verdict_reason=f"case execution ended before it recorded a run: {reason}",
        # No capture stage was reached, so the row carries a verdict and no
        # execution_status rather than a capture outcome.
        execution_status=None,
        case_outcome=case_outcome_for_verdict(INFLIGHT_CASE_FAILURE_VERDICT),
        started_at=started_at or now,
        completed_at=now,
        created_at=now,
    )


__all__ = [
    "CAPTURE_RUNNERS",
    "INFLIGHT_CASE_FAILURE_VERDICT",
    "UNREVIEWED_CAPTURE_REASON",
    "UNREVIEWED_CAPTURE_VERDICT",
    "record_inflight_case_failure",
    "settle_unreviewed_execution_captures",
    "stamp_reviewed_capture",
]
