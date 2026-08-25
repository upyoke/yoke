"""Closed Cursor adapter for relay-owned session creation and wakeup.

Native framing stays behind two small ports.  The relay passes only the
server-authored bootstrap or check-inbox sentence to either port; launch
attestation is a separate repr-hidden field and never enters native argv or
result evidence.  Until an installed Cursor build proves an exact framing,
the public default adapter fails closed without starting a process.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Protocol

from yoke_harness.session_relay_runtime import (
    expected_native_instruction,
    RelayAdapter,
    RelayAdapterResult,
    RelayExecutionContext,
    WakeMode,
    normalize_wake_mode,
    wake_operation,
)


CURSOR_ADAPTER_REVISION = "cursor-native-v2"
CURSOR_CLI_SURFACE = "cursor-cli"
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
class CursorCreateRequest:
    """One opaque create request; the attestation is never printable."""

    checkout: Path
    launch_id: str
    surface_version: str
    native_instruction: str = field(repr=False)
    launch_attestation: str = field(repr=False)
    requested_model: str | None = None


@dataclass(frozen=True)
class CursorWakeRequest:
    """One exact-session wake carrying only the check-inbox sentence."""

    checkout: Path
    target_session_id: str
    surface_version: str
    target_liveness: str | None
    wake_mode: WakeMode
    native_instruction: str = field(repr=False)

    def __post_init__(self) -> None:
        if normalize_wake_mode(self.wake_mode) is None:
            raise ValueError("wake instruction has no authorized mode")


@dataclass(frozen=True)
class CursorNativeResult:
    """Bounded native outcome with no stdout, stderr, prompt, or secret field."""

    result_code: str
    native_session_id: str | None = None
    exit_code: int | None = None
    duration_ms: int | None = None


class CursorSubprocessPort(Protocol):
    """The proven cursor-agent stopped-session resume operation.

    Creation is deliberately absent. A print-mode create detaches a native
    nobody owns: it runs outside the hook chain, so it never registers, and
    nothing is left holding the process when the launch is written off.
    Observed natives created that way read the backlog, adopted briefs meant
    for other sessions, and wrote into the shared checkout with no claim and
    no lane. Launches go through the caller-owned ACP port instead.
    """

    def resume_chat(self, request: CursorWakeRequest) -> CursorNativeResult: ...


class CursorAcpPort(Protocol):
    """Proven ACP session/new and caller-owned idle-session operations."""

    def new_session(self, request: CursorCreateRequest) -> CursorNativeResult: ...

    def prompt_session(self, request: CursorWakeRequest) -> CursorNativeResult: ...


def _evidence(
    result_code: str,
    native: CursorNativeResult | None = None,
) -> dict[str, str | int]:
    evidence: dict[str, str | int] = {
        "surface": CURSOR_CLI_SURFACE,
        "result_code": result_code,
    }
    if native is not None and native.exit_code is not None:
        evidence["exit_code"] = native.exit_code
    if native is not None and native.duration_ms is not None:
        evidence["duration_ms"] = max(0, native.duration_ms)
    return evidence


def _result(
    result_code: str,
    *,
    native: CursorNativeResult | None = None,
    native_session_id: str | None = None,
) -> RelayAdapterResult:
    return RelayAdapterResult(
        result_code,
        native_session_id=native_session_id,
        adapter_revision=CURSOR_ADAPTER_REVISION,
        evidence=_evidence(result_code, native),
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
    expected = expected_native_instruction(context)
    if expected is None or context.native_instruction != expected:
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
    acp_port: CursorAcpPort | None = None,
    version_gate: SurfaceVersionGate = _contract_version_gate,
) -> RelayAdapter:
    """Build one adapter over injected, version-pinned native transports.

    Launch goes only to ``acp_port``: the ACP child stays a child of the
    process that started it, so an exchange that cannot finish takes the
    native down with it rather than leaving one running unattended.
    """

    def adapter(context: RelayExecutionContext) -> RelayAdapterResult:
        refused = _validated(context, version_gate)
        if refused is not None:
            return refused
        if context.job_kind == "launch":
            request = CursorCreateRequest(
                checkout=context.checkout,
                launch_id=context.job_id,
                surface_version=str(context.surface_version),
                native_instruction=context.native_instruction,
                launch_attestation=str(context.launch_attestation),
                requested_model=context.requested_model,
            )
            if acp_port is None:
                return _result(
                    "not_created",
                    native=CursorNativeResult("native_framing_unavailable"),
                )
            try:
                return _launch_result(acp_port.new_session(request))
            except Exception:
                return _result("outcome_unknown")

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
        )
        operation = wake_operation(request.wake_mode, request.target_liveness)
        if operation == "message_idle" and acp_port is None:
            return _result(
                "failed", native=CursorNativeResult("native_framing_unavailable")
            )
        if operation == "message_idle" and acp_port is not None:
            try:
                idle = acp_port.prompt_session(request)
            except Exception:
                return _result("outcome_unknown")
            if idle.result_code != "not_found":
                return _wake_result(idle)
        if subprocess_port is None:
            return _result(
                "failed", native=CursorNativeResult("native_framing_unavailable")
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
    "CursorAcpPort",
    "CursorCreateRequest",
    "CursorNativeResult",
    "CursorSubprocessPort",
    "CursorWakeRequest",
    "build_cursor_adapter",
    "cursor_relay_adapter",
]
