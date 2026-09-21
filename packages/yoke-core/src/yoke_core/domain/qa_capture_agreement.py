"""``qa_runs.execution_status`` must agree with the artifacts it claims.

``captured`` means the run holds evidence: at least one ``qa_artifacts`` row,
or a named ``capture_degraded_reason`` when the capture produced none. A
``captured`` row with a NULL reason and zero artifacts is the disagreement
this module refuses. Leave ``execution_status`` unset when no capture was
attempted. ``capture_failed`` is a different status and does not need
artifacts; it must still name what failed to capture and why on the run.
"""

from __future__ import annotations

from typing import Any, Optional

from yoke_contracts.qa_execution_status import CAPTURED

CAPTURE_STATUS_ARTIFACT_DISAGREEMENT = "capture_status_artifact_disagreement"

NO_SCREENSHOT_ARTIFACTS_REASON = "no_screenshot_artifacts:case_produced_none"

AGENT_MISSION_DOCKET_REASON = (
    "agent_mission_docket:walker_artifacts_not_yet_attached"
)


def captured_without_evidence_error(
    *,
    execution_status: Optional[str],
    artifact_count: int,
    capture_degraded_reason: Optional[str],
) -> Optional[str]:
    """Return why ``captured`` disagrees with this run's evidence, else None."""
    if execution_status != CAPTURED:
        return None
    if int(artifact_count) > 0:
        return None
    if str(capture_degraded_reason or "").strip():
        return None
    return (
        "execution_status 'captured' claims a capture but this run has zero "
        "qa_artifacts and capture_degraded_reason is empty. Attach at least "
        "one artifact with `yoke qa artifact add`, or set "
        "capture_degraded_reason to name why the capture produced none; "
        "omit execution_status when no capture was attempted."
    )


def run_artifact_count(conn: Any, run_id: int) -> int:
    """Return how many ``qa_artifacts`` rows this run currently holds."""
    from yoke_core.domain.db_helpers import query_scalar
    from yoke_core.domain.qa_plan_execution_store import marker

    p = marker(conn)
    value = query_scalar(
        conn,
        f"SELECT COUNT(*) FROM qa_artifacts WHERE qa_run_id = {p}",
        (int(run_id),),
    )
    return int(value or 0)


def abort_if_captured_without_evidence(
    *,
    execution_status: Optional[str],
    artifact_count: int,
    capture_degraded_reason: Optional[str] = None,
    rollback: Any | None = None,
) -> None:
    """Exit the CLI writer when ``captured`` disagrees with the artifacts."""
    issue = captured_without_evidence_error(
        execution_status=execution_status,
        artifact_count=artifact_count,
        capture_degraded_reason=capture_degraded_reason,
    )
    if issue is None:
        return
    if rollback is not None:
        rollback()
    print(f"Error: {issue}", file=__import__("sys").stderr)
    raise SystemExit(2)


def degraded_reason_for_empty_capture(artifact_count: int) -> Optional[str]:
    """Name a zero-artifact capture, or None when artifacts exist."""
    if int(artifact_count) > 0:
        return None
    return NO_SCREENSHOT_ARTIFACTS_REASON


__all__ = [
    "AGENT_MISSION_DOCKET_REASON",
    "CAPTURE_STATUS_ARTIFACT_DISAGREEMENT",
    "NO_SCREENSHOT_ARTIFACTS_REASON",
    "abort_if_captured_without_evidence",
    "captured_without_evidence_error",
    "degraded_reason_for_empty_capture",
    "run_artifact_count",
]
