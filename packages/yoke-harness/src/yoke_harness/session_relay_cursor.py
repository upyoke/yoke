"""Closed Cursor adapter for relay-owned session creation and wakeup.

Native framing stays behind one small port.  The relay passes only the
server-authored bootstrap or check-inbox sentence to it; launch attestation
is a separate repr-hidden field and never enters native argv or result
evidence.  Until an installed Cursor build proves an exact framing, the
public default adapter fails closed without starting a process.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Protocol

from yoke_harness.session_relay_cursor_evidence import (
    CURSOR_CLI_SURFACE,
    cursor_evidence,
    cursor_private_diagnostic,
)
from yoke_harness.session_relay_cursor_requests import (
    CursorCreateRequest,
    CursorWakeRequest,
    cursor_model_selector,
)
from yoke_harness.session_relay_native_diagnostics import (
    MODEL_COMBO_UNSUPPORTED,
    model_combo_rejection_detail,
)
from yoke_harness.session_relay_runtime import (
    native_instruction_targets_job,
    RelayAdapter,
    RelayAdapterResult,
    RelayExecutionContext,
    normalize_wake_mode,
    wake_operation,
)


CURSOR_ADAPTER_REVISION = "cursor-native-v4"
SurfaceVersionGate = Callable[[str, str | None, str], bool]

_LAUNCH_CODES = frozenset({"native_created", "not_created", "outcome_unknown"})
_WAKE_CODES = frozenset(
    {
        "accepted",
        "failed",
        "not_found",
        "outcome_unknown",
        "unsupported_surface",
        "version_mismatch",
    }
)


@dataclass(frozen=True)
class CursorNativeResult:
    """Bounded native outcome; identity-parse tails stay out of repr."""

    result_code: str
    native_session_id: str | None = None
    exit_code: int | None = None
    duration_ms: int | None = None
    identity_output_snippet: str | None = field(default=None, repr=False)
    identity_parse_expectation: str | None = field(default=None, repr=False)
    phase: str | None = None
    # What the native wrote to stderr before it failed. Never reported over
    # the relay wire; the serve loop retains it machine-locally and reports
    # only an opaque reference.
    native_stderr: bytes = field(default=b"", repr=False)
    # Where a supervised turn's own account is being written, and the name it
    # is written under. A detached resume ends after the relay poll does, so
    # the reference is what lets any later reader find what it said.
    diagnostic_ref: str | None = None
    capture_path: str | None = None
    native_pid: int | None = None


class CursorSubprocessPort(Protocol):
    """One native new-chat create or exact-session print-mode resume."""

    def new_session(self, request: CursorCreateRequest) -> CursorNativeResult: ...

    def resume_chat(self, request: CursorWakeRequest) -> CursorNativeResult: ...


def _result(
    result_code: str,
    *,
    native: CursorNativeResult | None = None,
    native_session_id: str | None = None,
    evidence_code: str | None = None,
    probe_detail: str | None = None,
) -> RelayAdapterResult:
    return RelayAdapterResult(
        result_code,
        native_session_id=native_session_id,
        adapter_revision=CURSOR_ADAPTER_REVISION,
        evidence=cursor_evidence(
            evidence_code or result_code,
            native,
            probe_detail=probe_detail,
        ),
        private_diagnostic=cursor_private_diagnostic(native),
    )


def _contract_version_gate(
    surface: str,
    version: str | None,
    operation: str,
) -> bool:
    try:
        from yoke_contracts.session_control.surface_versions import (
            surface_operation_supported,
        )
    except (AttributeError, ImportError):
        return False
    return surface_operation_supported(surface, version, operation)


def _validated(
    context: RelayExecutionContext,
    version_gate: SurfaceVersionGate,
) -> RelayAdapterResult | None:
    if context.surface != CURSOR_CLI_SURFACE:
        return _result("unsupported_surface")
    if not native_instruction_targets_job(context):
        code = "not_created" if context.job_kind == "launch" else "failed"
        return _result(code, native=CursorNativeResult("instruction_refused"))
    if context.job_kind == "launch" and not context.launch_attestation:
        return _result("not_created", native=CursorNativeResult("attestation_missing"))
    version = str(context.surface_version or "").strip()
    if context.job_kind == "launch":
        operation = "create"
    else:
        operation = wake_operation(context.wake_mode, context.target_liveness)
        if not context.target_session_id:
            return _result("failed", native=CursorNativeResult("target_missing"))
        if operation is None:
            return _result("failed", native=CursorNativeResult("wake_mode_invalid"))
    if not version or not version_gate(context.surface, version, operation):
        code = "not_created" if context.job_kind == "launch" else "version_mismatch"
        return _result(code, native=CursorNativeResult("version_mismatch"))
    return None


def _launch_result(native: CursorNativeResult) -> RelayAdapterResult:
    detail = model_combo_rejection_detail(native.native_stderr)
    if detail:
        return _result(
            "not_created",
            native=native,
            evidence_code=MODEL_COMBO_UNSUPPORTED,
            probe_detail=detail,
        )
    if native.result_code not in _LAUNCH_CODES:
        return _result("outcome_unknown", native=native)
    if native.result_code == "native_created" and not native.native_session_id:
        return _result("outcome_unknown", native=native)
    return _result(
        native.result_code,
        native=native,
        native_session_id=native.native_session_id,
    )


def _wake_result(native: CursorNativeResult) -> RelayAdapterResult:
    code = (
        native.result_code if native.result_code in _WAKE_CODES else "outcome_unknown"
    )
    return _result(code, native=native)


def build_cursor_adapter(
    *,
    subprocess_port: CursorSubprocessPort | None = None,
    version_gate: SurfaceVersionGate = _contract_version_gate,
) -> RelayAdapter:
    """Build one adapter over an injected, version-pinned native transport.

    A create uses Cursor's native new-chat print path so ``sessionStart`` can
    register the vendor-created identity. A wake alone resumes an exact
    existing conversation. The launch adapter resolves the registered create
    through the relay's shared control-plane registration candidate surface.
    """

    def adapter(context: RelayExecutionContext) -> RelayAdapterResult:
        refused = _validated(context, version_gate)
        if refused is not None:
            return refused
        if subprocess_port is None:
            code = "not_created" if context.job_kind == "launch" else "failed"
            return _result(
                code, native=CursorNativeResult("native_framing_unavailable")
            )
        if context.job_kind == "launch":
            request = CursorCreateRequest(
                checkout=context.checkout,
                launch_id=context.job_id,
                surface_version=str(context.surface_version),
                native_instruction=context.native_instruction,
                launch_attestation=str(context.launch_attestation),
                requested_model=cursor_model_selector(context),
            )
            try:
                native = subprocess_port.new_session(request)
            except Exception:
                return _result(
                    "outcome_unknown",
                    native=CursorNativeResult("transport_exception", phase="spawn"),
                    evidence_code="transport_exception",
                )
            from yoke_harness.session_relay_cursor_registration import (
                complete_bound_launch,
            )

            return complete_bound_launch(context, native)

        wake_mode = normalize_wake_mode(context.wake_mode)
        if wake_mode is None:
            return _result("failed", native=CursorNativeResult("wake_mode_invalid"))
        request = CursorWakeRequest(
            checkout=context.checkout,
            target_session_id=str(context.target_session_id),
            surface_version=str(context.surface_version),
            target_liveness=context.target_liveness,
            wake_mode=wake_mode,
            native_instruction=context.native_instruction,
            requested_model=cursor_model_selector(context),
            attempt_id=str(context.job_id),
            lease_id=str(context.lease_id),
        )
        try:
            return _wake_result(subprocess_port.resume_chat(request))
        except Exception:
            return _result("outcome_unknown")

    return adapter


# Explicit ports are supplied by the lazy native-adapter registry.
cursor_relay_adapter: Callable[[RelayExecutionContext], RelayAdapterResult] = (
    build_cursor_adapter()
)


__all__ = [
    "CURSOR_ADAPTER_REVISION",
    "CURSOR_CLI_SURFACE",
    "CursorCreateRequest",
    "CursorNativeResult",
    "CursorSubprocessPort",
    "CursorWakeRequest",
    "build_cursor_adapter",
    "cursor_model_selector",
    "cursor_relay_adapter",
]
