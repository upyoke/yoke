"""Settle captured QA runs that a terminal plan execution would freeze."""

from __future__ import annotations

from typing import Any, Mapping

from yoke_core.domain.db_helpers import iso8601_now
from yoke_core.domain.qa_constants import case_outcome_for_verdict
from yoke_core.domain.qa_plan_execution_store import marker
from yoke_core.domain.schema_common import _table_exists


CAPTURE_RUNNERS = ("browser_substrate", "host_control", "agent_mission")
INFLIGHT_CASE_FAILURE_VERDICT = "error"
UNREVIEWED_CAPTURE_VERDICT = "error"
UNREVIEWED_CAPTURE_REASON = (
    "execution ended without a review verdict; capture settled by "
    "execution termination"
)


def stamp_reviewed_capture(
    conn: Any,
    case: Mapping[str, Any],
    *,
    verdict: str,
    rationale: str,
    created_at: str,
) -> None:
    """Copy the reviewed verdict onto the capture without changing its shape.

    Browser-evidence gates match an agent-reviewed capture on
    execution_status='captured' plus case_outcome='needs_review' plus a
    linked passing review row. The first stamp is allowed; a replay no-ops
    because the immutability trigger only fires once a verdict exists.
    """
    placeholder = marker(conn)
    conn.execute(
        "UPDATE qa_runs SET verdict="
        f"{placeholder},verdict_reason={placeholder},"
        "completed_at=COALESCE(completed_at, "
        f"{placeholder}) "
        f"WHERE id={placeholder} AND verdict IS NULL",
        (verdict, rationale, created_at, int(case["capture_run_id"])),
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
    conn.execute(
        "UPDATE qa_runs SET verdict="
        f"{placeholder},verdict_reason={placeholder},"
        "completed_at=COALESCE(completed_at, "
        f"{placeholder}) "
        f"WHERE qa_requirement_id IN ({req_placeholders}) "
        f"AND performed_by IN ({runners}) "
        "AND verdict IS NULL",
        (
            UNREVIEWED_CAPTURE_VERDICT,
            UNREVIEWED_CAPTURE_REASON,
            iso8601_now(),
            *requirement_ids,
            *CAPTURE_RUNNERS,
        ),
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
    from yoke_core.domain.qa_plan_execution_continuation import (
        CASE_EXECUTION_ERROR_REASON,
        CONTINUATION_PRE_HOST_ERROR_REASON,
    )

    if reason not in {
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
    conn.execute(
        "INSERT INTO qa_runs(qa_requirement_id,performed_by,qa_kind,verdict,"
        "verdict_reason,execution_status,case_outcome,started_at,completed_at,"
        f"created_at) VALUES({','.join([placeholder] * 10)})",
        (
            int(requirement_id),
            str(case.get("runner_id") or ""),
            str(case.get("qa_kind") or ""),
            INFLIGHT_CASE_FAILURE_VERDICT,
            f"case execution ended before it recorded a run: {reason}",
            # No capture stage was reached, so the row carries a verdict
            # and no execution_status rather than a capture outcome.
            None,
            case_outcome_for_verdict(INFLIGHT_CASE_FAILURE_VERDICT),
            started_at or now,
            now,
            now,
        ),
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
