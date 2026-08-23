"""Closed Claude CLI create and stopped-session wake routes."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import shutil
import subprocess
import time
from typing import Callable
from uuid import UUID

from yoke_harness.session_relay_runtime import (
    RelayAdapterResult,
    RelayExecutionContext,
)
from yoke_harness.session_relay_environment import native_session_environment


CLAUDE_ADAPTER_REVISION = "claude-native-v1"
CLAUDE_CLI_SURFACE = "claude-cli"
CLAUDE_NATIVE_TIMEOUT_SECONDS = 20
CLAUDE_UNSUPPORTED_SURFACES = frozenset({"claude-desktop", "claude-vscode"})


@dataclass(frozen=True)
class ClaudeNativeInvocation:
    """One bounded native call; its model-visible instruction stays out of repr."""

    executable: str
    cwd: Path
    session_id: str
    surface_version: str
    instruction: str = field(repr=False)
    resume: bool = False
    model: str | None = None
    launch_id: str | None = None
    launch_attestation: str | None = field(default=None, repr=False)

    @property
    def argv(self) -> tuple[str, ...]:
        session_flag = "--resume" if self.resume else "--session-id"
        arguments = [self.executable, session_flag, self.session_id]
        if self.model and not self.resume:
            arguments.extend(("--model", self.model))
        arguments.extend(("--bg", self.instruction))
        return tuple(arguments)


@dataclass(frozen=True)
class ClaudeProcessResult:
    """Sanitized process facts; native output is optional and never reported."""

    returncode: int
    duration_ms: int
    stdout: str = field(default="", repr=False)
    stderr: str = field(default="", repr=False)


ClaudeProcessRunner = Callable[[ClaudeNativeInvocation], ClaudeProcessResult]
ExecutableFinder = Callable[[str], str | None]
LaunchAttestationHandoff = Callable[[str, str], bool]
SurfaceVersionGate = Callable[[str, str | None, str], bool]


def discover_claude_cli(
    finder: ExecutableFinder = shutil.which,
) -> str | None:
    """Return the executable selected by the local command search path."""
    try:
        discovered = finder("claude")
    except (OSError, ValueError):
        return None
    return str(discovered).strip() if discovered else None


def run_claude_process(invocation: ClaudeNativeInvocation) -> ClaudeProcessResult:
    """Run one documented background command without retaining native output."""
    started = time.monotonic()
    environment = native_session_environment(
        executor="claude-code",
        executor_version=invocation.surface_version,
        provider="anthropic",
        markers={"CLAUDE_CODE_ENTRYPOINT": "cli"},
        launch_id=invocation.launch_id,
        launch_attestation=invocation.launch_attestation,
    )
    completed = subprocess.run(
        list(invocation.argv),
        cwd=invocation.cwd,
        env=environment,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=CLAUDE_NATIVE_TIMEOUT_SECONDS,
        check=False,
    )
    duration_ms = max(0, int((time.monotonic() - started) * 1000))
    return ClaudeProcessResult(completed.returncode, duration_ms)


def _contract_version_gate(
    surface: str,
    version: str | None,
    operation: str,
) -> bool:
    try:
        from yoke_contracts.session_control.surface_versions import (
            surface_operation_supported,
        )
    except (ImportError, AttributeError):
        return False
    return surface_operation_supported(surface, version, operation)


def _operation_supported(
    context: RelayExecutionContext,
    operation: str,
    gate: SurfaceVersionGate | None,
) -> bool:
    version = getattr(context, "surface_version", None)
    if not isinstance(version, str) or not version.strip():
        return False
    try:
        return bool(
            (gate or _contract_version_gate)(context.surface, version, operation)
        )
    except (TypeError, ValueError):
        return False


def _evidence(
    context: RelayExecutionContext,
    code: str,
    process: ClaudeProcessResult | None = None,
) -> dict[str, object]:
    evidence: dict[str, object] = {
        "result_code": code,
        "surface": context.surface,
    }
    if process is not None:
        evidence["duration_ms"] = max(0, min(process.duration_ms, 3_600_000))
        evidence["exit_code"] = int(process.returncode)
    return evidence


def _result(
    context: RelayExecutionContext,
    result_code: str,
    evidence_code: str,
    *,
    native_session_id: str | None = None,
    process: ClaudeProcessResult | None = None,
) -> RelayAdapterResult:
    return RelayAdapterResult(
        result_code,
        native_session_id=native_session_id,
        adapter_revision=CLAUDE_ADAPTER_REVISION,
        evidence=_evidence(context, evidence_code, process),
    )


def unsupported_claude_route(
    context: RelayExecutionContext,
) -> RelayAdapterResult:
    """Return the typed refusal for non-CLI Claude surfaces."""
    return _result(
        context,
        "not_created" if context.job_kind == "launch" else "unsupported_surface",
        "unsupported_surface",
    )


def _expected_instruction(context: RelayExecutionContext) -> str | None:
    if context.job_kind == "launch":
        return f"Yoke launch `{context.job_id}`: register, pull your message, act."
    if context.job_kind == "wake" and context.message_id:
        return f"Yoke message {context.message_id}: check your Yoke messages."
    return None


def _context_extensions_present(context: RelayExecutionContext) -> bool:
    return all(
        hasattr(context, field_name)
        for field_name in ("surface_version", "requested_model", "presentation")
    )


def _launch_invocation(
    context: RelayExecutionContext,
    executable: str,
    instruction: str,
    native_session_id: str,
    handoff: LaunchAttestationHandoff | None,
) -> ClaudeNativeInvocation | None:
    attestation = context.launch_attestation
    if not attestation or handoff is None:
        return None
    try:
        handed_off = handoff(context.job_id, attestation)
    except Exception:  # the secret must never be copied into failure evidence
        return None
    if not handed_off:
        return None
    raw_model = getattr(context, "requested_model", None)
    model = str(raw_model).strip() if raw_model else None
    return ClaudeNativeInvocation(
        executable,
        context.checkout,
        native_session_id,
        str(context.surface_version),
        instruction,
        model=model,
        launch_id=context.job_id,
        launch_attestation=attestation,
    )


def _wake_invocation(
    context: RelayExecutionContext,
    executable: str,
    instruction: str,
) -> ClaudeNativeInvocation | None:
    session_id = str(context.target_session_id or "").strip()
    if not session_id:
        return None
    return ClaudeNativeInvocation(
        executable,
        context.checkout,
        session_id,
        str(context.surface_version),
        instruction,
        resume=True,
    )


def run_claude_cli_adapter(
    context: RelayExecutionContext,
    *,
    process_runner: ClaudeProcessRunner = run_claude_process,
    executable_finder: ExecutableFinder = shutil.which,
    version_gate: SurfaceVersionGate | None = None,
    attestation_handoff: LaunchAttestationHandoff | None = None,
) -> RelayAdapterResult:
    """Create or wake exactly one Claude CLI session, failing closed."""
    if context.surface != CLAUDE_CLI_SURFACE:
        return unsupported_claude_route(context)
    if context.job_kind not in {"launch", "wake"}:
        return _result(context, "failed", "job_kind_invalid")
    if context.job_kind == "wake" and context.target_liveness != "ended":
        return _result(context, "unsupported_surface", "liveness_unsupported")
    operation = "create" if context.job_kind == "launch" else "message_stopped"
    if not _operation_supported(context, operation, version_gate):
        result = "not_created" if context.job_kind == "launch" else "version_mismatch"
        return _result(context, result, "version_mismatch")
    expected = _expected_instruction(context)
    if expected is None or context.native_instruction != expected:
        result = "not_created" if context.job_kind == "launch" else "failed"
        return _result(context, result, "instruction_invalid")
    executable = discover_claude_cli(executable_finder)
    if executable is None:
        result = "not_created" if context.job_kind == "launch" else "failed"
        return _result(context, result, "executable_unavailable")
    if context.job_kind == "launch":
        if not _context_extensions_present(context):
            return _result(context, "not_created", "context_incomplete")
        try:
            native_session_id = str(UUID(context.job_id))
        except (TypeError, ValueError, AttributeError):
            return _result(context, "not_created", "native_session_invalid")
        invocation = _launch_invocation(
            context,
            executable,
            expected,
            native_session_id,
            attestation_handoff,
        )
        if invocation is None:
            return _result(context, "not_created", "attestation_handoff_unavailable")
    else:
        invocation = _wake_invocation(context, executable, expected)
        if invocation is None:
            return _result(context, "not_found", "native_session_missing")
    try:
        process = process_runner(invocation)
    except Exception:  # native exceptions may contain prompts, output, or tokens
        result = "outcome_unknown" if context.job_kind == "launch" else "failed"
        return _result(context, result, "native_exception")
    if process.returncode != 0:
        result = "outcome_unknown" if context.job_kind == "launch" else "failed"
        return _result(context, result, "native_exit", process=process)
    if context.job_kind == "launch":
        return _result(
            context,
            "native_created",
            "native_created",
            native_session_id=invocation.session_id,
            process=process,
        )
    return _result(context, "accepted", "accepted", process=process)


__all__ = [
    "CLAUDE_ADAPTER_REVISION",
    "CLAUDE_CLI_SURFACE",
    "CLAUDE_NATIVE_TIMEOUT_SECONDS",
    "CLAUDE_UNSUPPORTED_SURFACES",
    "ClaudeNativeInvocation",
    "ClaudeProcessResult",
    "discover_claude_cli",
    "run_claude_cli_adapter",
    "run_claude_process",
    "unsupported_claude_route",
]
