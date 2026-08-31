"""Merge-path drift check, and what the landing records when it cannot run.

The comparison needs a readable declaration and a reachable GitHub; when
either is missing it cannot answer, and refusing the merge on an outage
would stop landings for a reason unrelated to the branch. It therefore
does not block — but "did not block" and "compared and agreed" are
different facts, and the batch receipt used to carry neither. The skip is
recorded twice now: once as its own audit event, and once on the batch
evidence every member of the train stores, so a landing that was never
compared says so where the evidence is read.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from yoke_contracts.api.function_call import TargetRef
from yoke_core.api.service_client_structured_api_adapter import call_dispatcher
from yoke_core.domain.merge_queue_live_drift import (
    LiveDriftReport,
    drift_blocking_landing,
)

MERGE_QUEUE_DRIFT_CHECK_SKIPPED_EVENT_NAME = "MergeQueueDriftCheckSkipped"


def _emit_drift_check_skipped(
    *,
    item_id: int,
    project: str,
    branch: str,
    report: LiveDriftReport,
) -> str:
    """Record one skipped comparison; return an advisory on write failure."""
    try:
        response = call_dispatcher(
            function_id="events.emit",
            target=TargetRef(kind="global"),
            payload={
                "name": MERGE_QUEUE_DRIFT_CHECK_SKIPPED_EVENT_NAME,
                "kind": "audit",
                "type": "merge_queue_drift_check",
                "source_type": "system",
                "severity": "WARN",
                "outcome": "skipped",
                "project": project,
                "item_id": str(int(item_id)),
                "context": {
                    "branch": branch,
                    "skip_reason": report.skip_reason,
                    "detail": report.skip_detail,
                },
            },
        )
    except Exception as exc:  # noqa: BLE001 -- telemetry never gates a merge
        return f"merge-queue drift skip event not recorded: {exc}"

    result: dict[str, Any] = response.result or {}
    if response.success and result.get("emitted") is True:
        return ""
    detail = (
        response.error.message
        if response.error is not None
        else str(result.get("reason") or "event write failed")
    )
    return f"merge-queue drift skip event not recorded: {detail}"


def drift_check_before_landing(
    project: str,
    *,
    checkout: str,
    branch: str,
    item_id: int,
) -> LiveDriftReport:
    """Run the gate and count every skipped comparison."""
    report = drift_blocking_landing(
        project,
        checkout=checkout,
        branch=branch,
    )
    if not report.skipped:
        return report
    advisory = _emit_drift_check_skipped(
        item_id=item_id,
        project=project,
        branch=branch,
        report=report,
    )
    if not advisory:
        return report
    return replace(report, unreadable=report.unreadable + (advisory,))


def drift_receipt(report: LiveDriftReport) -> dict[str, str]:
    """What the batch evidence records about this comparison."""
    if not report.skipped:
        return {"status": "compared"}
    return {
        "status": "skipped",
        "skip_reason": report.skip_reason,
        "detail": report.skip_detail,
    }


__all__ = [
    "MERGE_QUEUE_DRIFT_CHECK_SKIPPED_EVENT_NAME",
    "drift_check_before_landing",
    "drift_receipt",
]
