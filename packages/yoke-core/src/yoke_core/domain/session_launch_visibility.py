"""Canonical launch correlation and instruction-delivery states."""

from __future__ import annotations

from yoke_contracts.session_control.launch_registration import (
    BACKGROUND_IDENTITY_MISSING_CODE,
    IDENTITY_LISTING_FAILED_CODE,
    IDENTITY_LISTING_LAGGED_CODE,
    NATIVE_EXITED_UNREGISTERED_CODE,
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
# A launch whose native never ran its mandate: the vendor refused the
# requested combination, or the process was gone before any session
# registered. Both are visible on the fleet report the moment they are
# recorded, rather than only once the registration deadline passes.
LAUNCH_EXECUTION_FAILURE_CODES = frozenset(
    {
        "model_combo_unsupported",
        NATIVE_EXITED_UNREGISTERED_CODE,
        "native_capacity_unreadable",
        "native_memory_headroom_low",
        "native_swap_headroom_low",
    }
)
ACKNOWLEDGED_LAUNCH_PHASE = "registered_and_acknowledged"
# Only an acknowledged receipt can produce these outcome codes.
_ACKNOWLEDGED_RESULT_CODES = frozenset(
    {"launch_work_claim_missing", "launch_work_claim_pending"}
)


def launch_execution_failure_code(value: object) -> str:
    code = str(value or "").strip()
    return code if code in LAUNCH_EXECUTION_FAILURE_CODES else "native_create_failed"


def abandoned_launch_phase(state: str, result_code: str | None) -> str:
    """Name the phase an abandoned launch reached before its final outcome."""
    if state == "succeeded" or result_code == "launch_work_claim_pending":
        return ACKNOWLEDGED_LAUNCH_PHASE
    return state


def launch_visibility(
    *,
    state: str,
    result_code: str | None,
    native_session_id: str | None,
    registered_session_id: str | None,
    launch_phase_reached: str | None,
) -> dict[str, str]:
    """Describe correlation and delivery without inferring either from creation.

    A failed launch can still have delivered: its outcome code or recorded
    phase keeps the acknowledgement that the final state overwrote.
    """
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

    if (
        state == "succeeded"
        or result in _ACKNOWLEDGED_RESULT_CODES
        or (
            result == "abandoned_without_claim"
            and launch_phase_reached == ACKNOWLEDGED_LAUNCH_PHASE
        )
    ):
        delivery = "delivered"
    elif result == "injected_awaiting_acknowledgement":
        delivery = "awaiting_acknowledgement"
    elif state in TERMINAL_DELIVERY_STATES:
        delivery = "not_delivered"
    else:
        delivery = "pending"
    return {
        "identity_correlation": correlation,
        "instruction_delivery": delivery,
    }


__all__ = [
    "ACKNOWLEDGED_LAUNCH_PHASE",
    "CORRELATION_FAILURE_CODES",
    "LAUNCH_EXECUTION_FAILURE_CODES",
    "abandoned_launch_phase",
    "launch_execution_failure_code",
    "launch_visibility",
]
