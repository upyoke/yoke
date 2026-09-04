"""Retry and quarantine policy for durable terminal relay reports."""

from __future__ import annotations

import json
from pathlib import Path
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
)


Dispatcher = Callable[..., Any]
PERMANENT_REPORT_REJECTION_CODES = frozenset(
    {"payload_invalid", "relay_report_payload_invalid", "request_validation_failed"}
)


def response_error_code(response: Any) -> str:
    error = getattr(response, "error", None)
    return str(getattr(error, "code", None) or "relay_report_rejected")


def is_permanent_report_rejection(response: Any) -> bool:
    return response_error_code(response) in PERMANENT_REPORT_REJECTION_CODES


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
    "is_permanent_report_rejection",
    "response_error_code",
    "retry_pending_reports",
]
