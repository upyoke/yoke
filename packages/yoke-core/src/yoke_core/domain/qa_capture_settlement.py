"""Settle captured QA runs that a terminal plan execution would freeze."""

from __future__ import annotations

from typing import Any, Mapping

from yoke_core.domain.db_helpers import iso8601_now
from yoke_core.domain.qa_plan_execution_store import marker
from yoke_core.domain.schema_common import _table_exists


CAPTURE_RUNNERS = ("browser_substrate", "host_control", "agent_mission")
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


__all__ = [
    "CAPTURE_RUNNERS",
    "UNREVIEWED_CAPTURE_REASON",
    "UNREVIEWED_CAPTURE_VERDICT",
    "settle_unreviewed_execution_captures",
    "stamp_reviewed_capture",
]
