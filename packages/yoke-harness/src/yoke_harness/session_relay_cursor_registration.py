"""Bind a native Cursor create to the identity its opening hook registered."""

from __future__ import annotations

from dataclasses import replace

from yoke_harness.session_relay_cursor import (
    CursorNativeResult,
    _launch_result,
    _result,
)
from yoke_harness.session_relay_cursor_identity import resolve_registered_session
from yoke_harness.session_relay_runtime import RelayAdapterResult, RelayExecutionContext


def complete_bound_launch(
    context: RelayExecutionContext,
    native: object,
) -> RelayAdapterResult:
    """Resolve a vendor-created identity without inventing another protocol.

    The transport starts Cursor's native new-chat print path with no selected
    id. Its opening hook registers the id Cursor assigned. The relay's shared
    registration-candidate callback then resolves that session by launch,
    machine, surface, workspace, and time window. A still-missing candidate is
    an uncertain live native under existing supervision and deadline custody,
    not proof of either registration or failure.
    """
    typed = _as_native(native)
    if typed.result_code != "native_created":
        phase = typed.phase or "spawn"
        return _phased(_launch_result(typed), phase)

    resolution = resolve_registered_session(
        context.launch_registration_resolver,
        str(context.checkout),
    )
    pending = replace(
        typed,
        native_session_id=resolution.session_id,
        phase="registration_pending",
    )
    if resolution.session_id is None:
        return _result(
            "outcome_unknown",
            native=pending,
            evidence_code=resolution.result_code,
        )
    return _result(
        "native_created",
        native=pending,
        native_session_id=resolution.session_id,
        evidence_code=resolution.result_code,
    )


def _as_native(native: object) -> CursorNativeResult:
    if isinstance(native, CursorNativeResult):
        return native
    return CursorNativeResult(
        str(getattr(native, "result_code", "outcome_unknown")),
        getattr(native, "native_session_id", None),
        getattr(native, "exit_code", None),
        getattr(native, "duration_ms", None),
        identity_output_snippet=getattr(native, "identity_output_snippet", None),
        identity_parse_expectation=getattr(native, "identity_parse_expectation", None),
        phase=getattr(native, "phase", None),
        native_stderr=getattr(native, "native_stderr", b""),
        diagnostic_ref=getattr(native, "diagnostic_ref", None),
        capture_path=getattr(native, "capture_path", None),
        native_pid=getattr(native, "native_pid", None),
    )


def _phased(launched: RelayAdapterResult, phase: str) -> RelayAdapterResult:
    evidence = dict(launched.evidence)
    evidence.setdefault("native_launch_phase", phase)
    return RelayAdapterResult(
        launched.result_code,
        native_session_id=launched.native_session_id,
        adapter_revision=launched.adapter_revision,
        evidence=evidence,
        private_diagnostic=launched.private_diagnostic,
    )


__all__ = ["complete_bound_launch"]
