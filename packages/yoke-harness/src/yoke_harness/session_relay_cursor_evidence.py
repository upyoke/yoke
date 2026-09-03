"""Turn one cursor native outcome into evidence and a retainable diagnostic.

Kept apart from the adapter because both halves are about what may leave this
machine: the bounded facts a report carries, and the streams that stay behind
an opaque reference.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from yoke_harness.session_relay_native_diagnostics import classify_native_failure
from yoke_harness.session_relay_runtime import RelayPrivateDiagnostic

if TYPE_CHECKING:  # the adapter imports this module, so the type stays a name
    from yoke_harness.session_relay_cursor import CursorNativeResult


#: The surface every one of these facts describes, and the only one this
#: adapter family serves.
CURSOR_CLI_SURFACE = "cursor-cli"


def cursor_evidence(
    result_code: str,
    native: "CursorNativeResult | None" = None,
) -> dict[str, str | int]:
    evidence: dict[str, str | int] = {
        "surface": CURSOR_CLI_SURFACE,
        "result_code": result_code,
    }
    if native is None:
        return evidence
    if native.exit_code is not None:
        evidence["exit_code"] = native.exit_code
    if native.duration_ms is not None:
        evidence["duration_ms"] = max(0, native.duration_ms)
    for source, reported in (
        ("diagnostic_ref", "native_diagnostic_ref"),
        ("capture_path", "native_capture_path"),
    ):
        value = getattr(native, source, None)
        if isinstance(value, str) and value:
            evidence[reported] = value
    snippet = getattr(native, "identity_output_snippet", None)
    expectation = getattr(native, "identity_parse_expectation", None)
    if snippet:
        evidence["identity_output_snippet"] = snippet
    if expectation:
        evidence["identity_parse_expectation"] = expectation
    phase = getattr(native, "phase", None)
    if phase:
        evidence["native_launch_phase"] = phase
    store = getattr(native, "conversation_store", None)
    if store:
        evidence["conversation_store"] = store
    return evidence


def cursor_private_diagnostic(
    native: "CursorNativeResult | None",
) -> RelayPrivateDiagnostic | None:
    """Carry the native's own words to the machine-local retention layer."""
    stderr = bytes(getattr(native, "native_stderr", b"") or b"")
    if not stderr:
        return None
    return RelayPrivateDiagnostic(
        classify_native_failure(stderr),
        error_step="native_command",
        stderr=stderr,
    )


__all__ = [
    "CURSOR_CLI_SURFACE",
    "cursor_evidence",
    "cursor_private_diagnostic",
]
