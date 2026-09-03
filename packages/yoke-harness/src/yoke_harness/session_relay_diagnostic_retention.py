"""Keep a native spawn's streams on the machine and report only a handle.

Every spawn is retained, not only the ones that already failed. A launch
that reports success and whose native then dies before it ever works has
no second chance to explain itself, and the account it left behind on the
way up is the only one anybody will ever get.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from yoke_contracts.session_control.launch_registration import (
    BACKGROUND_IDENTITY_MISSING_CODE,
    IDENTITY_LISTING_LAGGED_CODE,
)
from yoke_harness.session_relay_native_diagnostics import (
    NativeDiagnosticError,
    diagnostic_reference,
    store_native_diagnostic,
)
from yoke_harness.session_relay_native_capture_format import capture_tail
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
    attempt_id: str,
    state_dir: Path | None,
    relay_id: str | None = None,
    machine_id: str | None = None,
) -> RelayAdapterResult:
    """Store the private streams under this job's own name and report a handle.

    ``attempt_id`` is the launch id for a spawn and the wake attempt id for a
    resume, which is what the capture is named after. Nothing else records
    where the file went, so a reader holding either identifier can still find
    what the native said.
    """
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
    exit_code = result.evidence.get("exit_code")
    try:
        receipt = store_native_diagnostic(
            private.stdout,
            private.stderr,
            reference=diagnostic_reference(attempt_id),
            exit_code=exit_code if isinstance(exit_code, int) else None,
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
    # The last line the native said, so a seat reading a fleet row on another
    # machine sees the reason without fetching the file it cannot reach.
    tail = capture_tail(private.stderr) or capture_tail(private.stdout)
    if tail:
        evidence["native_stderr_tail"] = tail
    return replace(result, evidence=evidence, private_diagnostic=None)


__all__ = [
    "NATIVE_ERROR_STEPS",
    "NATIVE_FAILURE_CLASSES",
    "retain_private_diagnostic",
]
