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
import time
from typing import Callable, Protocol

from yoke_harness.session_relay_cursor_evidence import (
    CURSOR_CLI_SURFACE,
    cursor_evidence,
    cursor_private_diagnostic,
)
from yoke_harness.session_relay_cursor_identity import (
    ConversationLookup,
    LaunchAttestationHandoff,
    conversation_map_lookup,
)
from yoke_harness.session_relay_runtime import (
    native_instruction_targets_job,
    RelayAdapter,
    RelayAdapterResult,
    RelayExecutionContext,
    WakeMode,
    normalize_wake_mode,
    wake_operation,
)


CURSOR_ADAPTER_REVISION = "cursor-native-v2"
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
    """One exact-session resume carrying only the check-inbox sentence.

    ``requested_model`` is the variant this turn must run under. cursor-agent
    resumes a session at whichever model it last ran, so naming it once — on
    the launch's own first resume — is what makes every later wake inherit it.
    """

    checkout: Path
    target_session_id: str
    surface_version: str
    target_liveness: str | None
    wake_mode: WakeMode
    native_instruction: str = field(repr=False)
    requested_model: str | None = None
    # The wake attempt this turn belongs to, and the lease it was claimed
    # under. The supervisor names the turn's capture after the attempt, and
    # the settlement that reports how it ended needs the lease to do so.
    attempt_id: str = ""
    lease_id: str = ""

    def __post_init__(self) -> None:
        if normalize_wake_mode(self.wake_mode) is None:
            raise ValueError("wake instruction has no authorized mode")


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
    # Which store the conversation lives in ("acp" — the only transport a
    # launch creates through). Recorded so a later resume knows what to
    # look for instead of guessing across transports.
    conversation_store: str | None = None
    # What the native wrote to stderr before it failed. Never reported over
    # the relay wire; the serve loop retains it machine-locally and reports
    # only an opaque reference.
    native_stderr: bytes = field(default=b"", repr=False)
    # Where a supervised turn's own account is being written, and the name it
    # is written under. A detached resume ends after the relay poll does, so
    # the reference is what lets any later reader find what it said.
    diagnostic_ref: str | None = None
    capture_path: str | None = None


class CursorSubprocessPort(Protocol):
    """Stopped-session resume. Print-mode create is absent; launches use ACP."""

    def resume_chat(self, request: CursorWakeRequest) -> CursorNativeResult: ...


class CursorAcpPort(Protocol):
    """Proven ACP session/new and caller-owned idle-session operations."""

    def new_session(self, request: CursorCreateRequest) -> CursorNativeResult: ...

    def prompt_session(self, request: CursorWakeRequest) -> CursorNativeResult: ...


def _result(
    result_code: str,
    *,
    native: CursorNativeResult | None = None,
    native_session_id: str | None = None,
    evidence_code: str | None = None,
) -> RelayAdapterResult:
    return RelayAdapterResult(
        result_code,
        native_session_id=native_session_id,
        adapter_revision=CURSOR_ADAPTER_REVISION,
        evidence=cursor_evidence(evidence_code or result_code, native),
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
    identity_lookup: ConversationLookup | None = None,
    attestation_handoff: LaunchAttestationHandoff | None = None,
    sleeper: Callable[[float], None] = time.sleep,
) -> RelayAdapter:
    """Build one adapter over injected, version-pinned native transports.

    Launch goes only to ``acp_port``: the ACP child stays a child of the
    process that started it, so an exchange that cannot finish takes the
    native down with it rather than leaving one running unattended.
    After create, the adapter binds the conversation-map session and
    stages the attestation sidecar under that id.
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
                native = acp_port.new_session(request)
            except Exception:
                return _result(
                    "outcome_unknown",
                    native=CursorNativeResult("transport_exception", phase="spawn"),
                    evidence_code="transport_exception",
                )
            from yoke_harness.session_relay_cursor_registration import (
                complete_bound_launch,
            )

            return complete_bound_launch(
                context,
                native,
                identity_lookup or conversation_map_lookup,
                attestation_handoff,
                sleeper,
            )

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
            requested_model=context.requested_model,
            attempt_id=str(context.job_id),
            lease_id=str(context.lease_id),
        )
        operation = wake_operation(request.wake_mode, request.target_liveness)
        if operation == "message_idle":
            if acp_port is None:
                return _result(
                    "failed", native=CursorNativeResult("native_framing_unavailable")
                )
            try:
                idle = acp_port.prompt_session(request)
            except Exception:
                return _result("outcome_unknown")
            # ACP session/load is authoritative here: "not_found" means the
            # store is gone, not a cue to let another transport recreate a
            # competing conversation under the same id.
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
