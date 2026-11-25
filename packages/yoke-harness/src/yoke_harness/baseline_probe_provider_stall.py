"""A real-request probe that started, then heard nothing back, retries once.

A timeout whose sanitized record shows events and no error event means the
harness started and no reply or error came back. It does not prove a reply
stream opened: the harnesses print their start events before any network
call, so a blocked network path on the host looks the same. One such stall
per probe run waits and re-runs its probe; a stall with no retry left reads
as ``harness_provider_unavailable`` rather than a failed baseline.
"""

from __future__ import annotations

from typing import Any

from yoke_contracts.harness_provider_unavailable import (
    PROVIDER_UNAVAILABLE_ERROR_CODE,
)
from yoke_harness.baseline_probe_failure_causes import REQUEST_TIMED_OUT

STALL_RETRY_DELAY_SECONDS = 60

NO_VERDICT_ERROR_CODE = "baseline_probe_bridge_unavailable"
FAILED_ERROR_CODE = "baseline_probe_failed"
BRIDGE_UNDELIVERED_CAUSE = "macos_gui_session_context_unavailable"


def provider_stalled(failure: dict[str, Any]) -> bool:
    """True when the harness started and neither a reply nor an error came back."""
    record = failure.get("reply_rejection") or {}
    return (
        failure.get("cause") == REQUEST_TIMED_OUT.cause
        and int(record.get("event_count") or 0) > 0
        and int(record.get("error_event_count") or 0) == 0
    )


def failure_error_code(failure: dict[str, Any]) -> str:
    """The run's error code for its final, unretried probe failure."""
    if failure.get("cause") == BRIDGE_UNDELIVERED_CAUSE:
        return NO_VERDICT_ERROR_CODE
    if provider_stalled(failure):
        return PROVIDER_UNAVAILABLE_ERROR_CODE
    return FAILED_ERROR_CODE


__all__ = [
    "BRIDGE_UNDELIVERED_CAUSE",
    "FAILED_ERROR_CODE",
    "NO_VERDICT_ERROR_CODE",
    "PROVIDER_UNAVAILABLE_ERROR_CODE",
    "STALL_RETRY_DELAY_SECONDS",
    "failure_error_code",
    "provider_stalled",
]
