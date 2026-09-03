"""Canonical launch correlation and instruction-delivery states."""

from __future__ import annotations

from yoke_contracts.session_control.launch_registration import (
    BACKGROUND_IDENTITY_MISSING_CODE,
    IDENTITY_LISTING_FAILED_CODE,
    IDENTITY_LISTING_LAGGED_CODE,
    REGISTERED_SESSION_INVALID_CODE,
    REGISTRATION_AMBIGUOUS_CODE,
    SPAWN_WORKSPACE_MISSING_CODE,
)
from yoke_core.domain.session_launch_delivery_state import TERMINAL_DELIVERY_STATES


CORRELATION_FAILURE_CODES = frozenset(
    {
        BACKGROUND_IDENTITY_MISSING_CODE,
        "identity_parse_failed",
        IDENTITY_LISTING_FAILED_CODE,
        IDENTITY_LISTING_LAGGED_CODE,
        "machine_mismatch",
        "native_session_mismatch",
        "project_mismatch",
        REGISTERED_SESSION_INVALID_CODE,
        REGISTRATION_AMBIGUOUS_CODE,
        SPAWN_WORKSPACE_MISSING_CODE,
        "surface_mismatch",
    }
)
LAUNCH_EXECUTION_FAILURE_CODES = frozenset({"model_combo_unsupported"})


def launch_execution_failure_code(value: object) -> str:
    code = str(value or "").strip()
    return code if code in LAUNCH_EXECUTION_FAILURE_CODES else "native_create_failed"


def launch_visibility(
    *,
    state: str,
    result_code: str | None,
    native_session_id: str | None,
    registered_session_id: str | None,
) -> dict[str, str]:
    """Describe correlation and delivery without inferring either from creation."""
    native = str(native_session_id or "").strip()
    registered = str(registered_session_id or "").strip()
    result = str(result_code or "").strip()
    if native and registered:
        correlation = "matched" if native == registered else "mismatch"
    elif result in CORRELATION_FAILURE_CODES:
        correlation = "correlation_failed"
    elif native:
        correlation = (
            "registration_failed"
            if state in TERMINAL_DELIVERY_STATES
            else "awaiting_registration"
        )
    elif registered:
        correlation = "native_unreported"
    elif state in TERMINAL_DELIVERY_STATES:
        correlation = "unavailable"
    else:
        correlation = "pending"

    if state == "succeeded":
        delivery = "delivered"
    elif state in TERMINAL_DELIVERY_STATES:
        delivery = "not_delivered"
    else:
        delivery = "pending"
    return {
        "identity_correlation": correlation,
        "instruction_delivery": delivery,
    }


__all__ = [
    "CORRELATION_FAILURE_CODES",
    "LAUNCH_EXECUTION_FAILURE_CODES",
    "launch_execution_failure_code",
    "launch_visibility",
]
