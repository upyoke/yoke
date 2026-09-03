"""Keep a native failure's streams on the machine and report only a handle."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from yoke_contracts.session_control.launch_registration import (
    BACKGROUND_IDENTITY_MISSING_CODE,
    IDENTITY_LISTING_LAGGED_CODE,
)
from yoke_harness.session_relay_native_diagnostics import (
    NativeDiagnosticError,
    store_native_diagnostic,
)
from yoke_harness.session_relay_runtime import RelayAdapterResult


NATIVE_FAILURE_CLASSES = frozenset(
    {
        "adapter_exception",
        BACKGROUND_IDENTITY_MISSING_CODE,
        "background_session_in_use",
        IDENTITY_LISTING_LAGGED_CODE,
        "identity_parse_failed",
        "native_exception",
        "no_conversation_found",
        "process_exit",
    }
)
NATIVE_ERROR_STEPS = frozenset(
    {
        "launch",
        "native_command",
        "resume",
        "session_lookup",
        "session_stop",
        "state_poll",
    }
)


def retain_private_diagnostic(
    result: RelayAdapterResult,
    *,
    state_dir: Path | None,
    relay_id: str | None = None,
    machine_id: str | None = None,
) -> RelayAdapterResult:
    """Store the private streams and return a result safe to report."""
    private = result.private_diagnostic
    if private is None:
        return result
    failure_class = (
        private.failure_class
        if private.failure_class in NATIVE_FAILURE_CLASSES
        else "adapter_exception"
    )
    evidence = dict(result.evidence)
    evidence["native_error_class"] = failure_class
    evidence["native_error_step"] = (
        private.error_step
        if private.error_step in NATIVE_ERROR_STEPS
        else "native_command"
    )
    if relay_id:
        evidence["relay_id"] = relay_id
    if machine_id:
        evidence["machine_id"] = machine_id
    try:
        receipt = store_native_diagnostic(
            private.stdout,
            private.stderr,
            state_dir=state_dir,
        )
    except NativeDiagnosticError:
        evidence["diagnostic_availability"] = "unavailable"
    else:
        evidence.update(
            {
                "diagnostic_availability": "relay_local",
                "diagnostic_expires_at": receipt.expires_at,
                "native_diagnostic_ref": receipt.reference,
                "native_error_sha256": receipt.fingerprint_sha256,
            }
        )
    return replace(result, evidence=evidence, private_diagnostic=None)


__all__ = [
    "NATIVE_ERROR_STEPS",
    "NATIVE_FAILURE_CLASSES",
    "retain_private_diagnostic",
]
