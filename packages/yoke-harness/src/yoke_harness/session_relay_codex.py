"""Version-gated Codex native-session operations for the machine relay.

The adapter owns policy and result translation.  Native subprocess and
app-server details live behind narrow ports so tests never create a real task.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Literal, Protocol

from yoke_harness.session_relay_runtime import (
    RelayAdapter,
    RelayAdapterResult,
    register_relay_adapter,
)


ADAPTER_REVISION = "codex-relay-v1"
CODEX_SURFACES = ("codex-cli", "codex-desktop")
_LIVENESS_OPERATION = {
    "active": "message_active",
    "stale": "message_idle",
    "ended": "message_stopped",
}
_MISSING = object()

VersionGate = Callable[[str | None, str | None, str], bool]
NativeState = Literal[
    "accepted",
    "failed",
    "not_created",
    "not_found",
    "outcome_unknown",
    "unsupported_surface",
]


@dataclass(frozen=True)
class CodexNativeRequest:
    """One closed native operation; secrets and prompts stay out of repr."""

    job_kind: str
    job_id: str
    surface: str
    surface_version: str
    checkout: Path
    requested_model: str | None
    presentation: str | None
    target_liveness: str | None
    target_session_id: str | None
    native_instruction: str = field(repr=False)
    launch_attestation: str | None = field(default=None, repr=False)


@dataclass(frozen=True)
class CodexNativeOutcome:
    """Bounded native fact set; never carries subprocess output."""

    state: NativeState
    native_session_id: str | None = None
    identity_correlated: bool = False
    exit_code: int | None = None


class CodexNativeTransport(Protocol):
    def create(self, request: CodexNativeRequest) -> CodexNativeOutcome: ...

    def wake(self, request: CodexNativeRequest) -> CodexNativeOutcome: ...


def _shared_version_gate(surface: str | None, version: str | None, operation: str) -> bool:
    """Load the contracts comparator lazily so mixed-version installs close."""
    try:
        from yoke_contracts.session_control.surface_versions import (
            surface_operation_supported,
        )
    except ImportError:
        return False
    return surface_operation_supported(surface, version, operation)


def _extended(context: Any, name: str) -> Any:
    value = getattr(context, name, _MISSING)
    if value is _MISSING:
        raise ValueError(f"relay context is missing {name}")
    return value


def _text(value: Any) -> str | None:
    rendered = str(value or "").strip()
    return rendered or None


def _request(context: Any) -> tuple[CodexNativeRequest, str]:
    surface = str(context.surface or "")
    if surface not in CODEX_SURFACES:
        raise ValueError("not a Codex relay surface")
    version = _text(_extended(context, "surface_version"))
    if version is None:
        raise ValueError("relay context has no surface version")
    requested_model = _text(_extended(context, "requested_model"))
    presentation = _text(_extended(context, "presentation"))
    liveness = _text(_extended(context, "target_liveness"))
    instruction = str(context.native_instruction or "").strip()
    if not instruction:
        raise ValueError("relay context has no native instruction")
    if context.job_kind == "launch":
        operation = "create"
        if not _text(context.launch_attestation):
            raise ValueError("launch context has no attestation side channel")
    elif context.job_kind == "wake":
        operation = _LIVENESS_OPERATION.get(str(liveness or ""), "")
        if not operation or not _text(context.target_session_id):
            raise ValueError("wake context has no exact target or liveness")
    else:
        raise ValueError("Codex relay job must be launch or wake")
    return (
        CodexNativeRequest(
            job_kind=str(context.job_kind),
            job_id=str(context.job_id),
            surface=surface,
            surface_version=version,
            checkout=Path(context.checkout),
            requested_model=requested_model,
            presentation=presentation,
            target_liveness=liveness,
            target_session_id=_text(context.target_session_id),
            native_instruction=instruction,
            launch_attestation=_text(context.launch_attestation),
        ),
        operation,
    )


def _evidence(surface: str, state: str, exit_code: int | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {"surface": surface, "result_code": state}
    if exit_code is not None:
        payload["exit_code"] = int(exit_code)
    return payload


def _translate(request: CodexNativeRequest, outcome: CodexNativeOutcome) -> RelayAdapterResult:
    evidence = _evidence(request.surface, outcome.state, outcome.exit_code)
    if outcome.state == "accepted" and not outcome.identity_correlated:
        return RelayAdapterResult(
            "outcome_unknown",
            adapter_revision=ADAPTER_REVISION,
            evidence=_evidence(request.surface, "identity_uncorrelated"),
        )
    if request.job_kind == "launch":
        if outcome.state == "accepted" and outcome.native_session_id:
            return RelayAdapterResult(
                "native_created",
                native_session_id=outcome.native_session_id,
                adapter_revision=ADAPTER_REVISION,
                evidence=evidence,
            )
        code = "not_created" if outcome.state == "not_created" else "outcome_unknown"
        return RelayAdapterResult(code, adapter_revision=ADAPTER_REVISION, evidence=evidence)
    code = {
        "accepted": "accepted",
        "not_found": "not_found",
        "unsupported_surface": "unsupported_surface",
        "outcome_unknown": "outcome_unknown",
    }.get(outcome.state, "failed")
    return RelayAdapterResult(code, adapter_revision=ADAPTER_REVISION, evidence=evidence)


def build_codex_relay_adapter(
    *,
    cli_transport: CodexNativeTransport,
    desktop_transport: CodexNativeTransport,
    version_gate: VersionGate = _shared_version_gate,
) -> RelayAdapter:
    """Return the closed adapter over explicitly supplied native ports."""

    def run(context: Any) -> RelayAdapterResult:
        try:
            request, operation = _request(context)
        except (AttributeError, TypeError, ValueError):
            kind = str(getattr(context, "job_kind", ""))
            code = "not_created" if kind == "launch" else "failed"
            return RelayAdapterResult(
                code,
                adapter_revision=ADAPTER_REVISION,
                evidence={"result_code": "context_incomplete"},
            )
        if not version_gate(request.surface, request.surface_version, operation):
            code = "not_created" if request.job_kind == "launch" else "version_mismatch"
            return RelayAdapterResult(
                code,
                adapter_revision=ADAPTER_REVISION,
                evidence=_evidence(request.surface, "version_mismatch"),
            )
        transport = cli_transport if request.surface == "codex-cli" else desktop_transport
        try:
            outcome = (
                transport.create(request)
                if request.job_kind == "launch"
                else transport.wake(request)
            )
        except Exception:
            code = "outcome_unknown" if request.job_kind == "launch" else "failed"
            return RelayAdapterResult(
                code,
                adapter_revision=ADAPTER_REVISION,
                evidence=_evidence(request.surface, "transport_exception"),
            )
        return _translate(request, outcome)

    return run


def register_codex_relay_adapters() -> None:
    """Register both Codex surfaces; the shared startup lane invokes this."""
    from yoke_harness.session_relay_codex_app_server import CodexAppServerTransport
    from yoke_harness.session_relay_codex_cli import CodexCliTransport

    adapter = build_codex_relay_adapter(
        cli_transport=CodexCliTransport(),
        desktop_transport=CodexAppServerTransport(),
    )
    for surface in CODEX_SURFACES:
        register_relay_adapter(surface, adapter)


__all__ = [
    "ADAPTER_REVISION",
    "CODEX_SURFACES",
    "CodexNativeOutcome",
    "CodexNativeRequest",
    "CodexNativeTransport",
    "build_codex_relay_adapter",
    "register_codex_relay_adapters",
]
