"""Retry and quarantine policy for durable terminal relay reports."""

from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any, Callable

from yoke_contracts.api.function_call import TargetRef
from yoke_harness import session_relay_report_delivery as delivery
from yoke_harness.session_relay_health import (
    REPORT_QUARANTINE_ATTEMPTS,
    clear_report_attempt,
    clear_report_failure_if_drained,
    quarantine_report,
    record_rejected_attempt,
    record_report_failure,
    report_rejection_evidence,
)


Dispatcher = Callable[..., Any]
PERMANENT_REPORT_REJECTION_CODES = frozenset(
    {
        "payload_invalid",
        "relay_report_payload_invalid",
        "report_conflict",
        "request_validation_failed",
    }
)
_REPORT_ID_PATTERN = re.compile(r"[0-9a-f]{64}")


class PendingReportQuarantineError(ValueError):
    """A targeted report cannot safely enter the permanent-rejection quarantine."""

    def __init__(self, code: str, message: str, recovery: str) -> None:
        super().__init__(message)
        self.code = code
        self.recovery = recovery


def response_error_code(response: Any) -> str:
    error = getattr(response, "error", None)
    return str(getattr(error, "code", None) or "relay_report_rejected")


def is_permanent_report_rejection(response: Any) -> bool:
    return response_error_code(response) in PERMANENT_REPORT_REJECTION_CODES


def quarantine_pending_report(
    report_id: str,
    *,
    state_dir: Path | None,
) -> dict[str, object]:
    """Preserve one pending report after a recorded permanent server rejection."""
    if _REPORT_ID_PATTERN.fullmatch(str(report_id or "")) is None:
        raise PendingReportQuarantineError(
            "relay_report_id_invalid",
            "report id must be the 64-character lowercase opaque id",
            "Copy the report id exactly from relay diagnostics.",
        )
    path = delivery._directory(state_dir) / f"{report_id}.json"
    if not path.is_file():
        raise PendingReportQuarantineError(
            "relay_report_not_pending",
            f"pending relay report {report_id} does not exist",
            "Run `yoke relay status --json`; do not recreate a settled report.",
        )
    rejection = report_rejection_evidence(path, state_dir)
    error_code = str(rejection.get("error_code") or "")
    if error_code not in PERMANENT_REPORT_REJECTION_CODES:
        raise PendingReportQuarantineError(
            "relay_report_quarantine_not_allowed",
            "the report has no recorded permanent server rejection",
            "Leave the relay running; connectivity and ambiguous failures must retry.",
        )
    try:
        safe = delivery._safe_payload(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        safe = None
    metadata = quarantine_report(
        path,
        safe,
        state_dir,
        error_code=error_code,
        attempts=int(rejection.get("attempts") or 1),
    )
    if not metadata.get("payload_sha256"):
        raise PendingReportQuarantineError(
            "relay_report_quarantine_failed",
            f"relay report {report_id} was not verified in quarantine",
            "Check relay state-directory permissions, then retry this exact report id.",
        )
    return metadata


def retry_pending_reports(
    dispatcher: Dispatcher,
    function_id: str,
    *,
    state_dir: Path | None,
    timeout_s: int,
) -> bool:
    """Drain retryable reports; quarantine bounded contract rejections."""
    directory = delivery._directory(state_dir)
    all_drained = True
    for path in sorted(directory.glob("*.json")):
        try:
            safe = delivery._safe_payload(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            safe = None
        if safe is None:
            quarantine_report(
                path,
                None,
                state_dir,
                error_code="pending_report_invalid",
                attempts=1,
            )
            continue
        try:
            response = dispatcher(
                function_id=function_id,
                target=TargetRef(kind="global"),
                payload=dict(safe),
                timeout_s=timeout_s,
            )
        except Exception:
            record_report_failure(state_dir, error_code="transport_error")
            all_drained = False
            continue
        if getattr(response, "success", False):
            path.unlink(missing_ok=True)
            clear_report_attempt(path, state_dir)
            continue
        code = response_error_code(response)
        if not is_permanent_report_rejection(response):
            record_report_failure(state_dir, error_code=code)
            all_drained = False
            continue
        attempts = record_rejected_attempt(
            path,
            state_dir,
            error_code=code,
        )
        if attempts < REPORT_QUARANTINE_ATTEMPTS:
            all_drained = False
            continue
        quarantine_report(
            path,
            safe,
            state_dir,
            error_code=code,
            attempts=attempts,
        )
    if all_drained:
        clear_report_failure_if_drained(state_dir)
    return all_drained


__all__ = [
    "PERMANENT_REPORT_REJECTION_CODES",
    "PendingReportQuarantineError",
    "is_permanent_report_rejection",
    "quarantine_pending_report",
    "response_error_code",
    "retry_pending_reports",
]
