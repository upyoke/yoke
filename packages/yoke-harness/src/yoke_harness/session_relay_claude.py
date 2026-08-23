"""Closed Claude CLI create and stopped-session wake routes."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
import re
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
_MAX_NATIVE_OUTPUT_BYTES = 64 * 1024
_BACKGROUND_ID_PATTERN = re.compile(
    r"(?im)^\s*backgrounded\s*[·:]\s*([A-Za-z0-9_-]{4,64})\s*$"
)


@dataclass(frozen=True)
class ClaudeNativeInvocation:
    executable: str
    cwd: Path
    session_id: str
    surface_version: str
    instruction: str = field(repr=False)
    resume: bool = False
    model: str | None = None

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
    returncode: int
    duration_ms: int
    stdout: str = field(default="", repr=False)
    stderr: str = field(default="", repr=False)


ClaudeProcessRunner = Callable[[ClaudeNativeInvocation], ClaudeProcessResult]
ClaudeSessionLookup = Callable[[ClaudeNativeInvocation], ClaudeProcessResult]
ExecutableFinder = Callable[[str], str | None]
SurfaceVersionGate = Callable[[str, str | None, str], bool]
LaunchAttestationHandoff = Callable[..., bool]


def discover_claude_cli(
    finder: ExecutableFinder = shutil.which,
) -> str | None:
    """Return the executable selected by the local command search path."""
    try:
        discovered = finder("claude")
    except (OSError, ValueError):
        return None
    return str(discovered).strip() if discovered else None


def _bounded_text(value: object) -> str:
    raw = value if isinstance(value, bytes) else str(value or "").encode()
    return raw[:_MAX_NATIVE_OUTPUT_BYTES].decode("utf-8", errors="replace")


def _run_claude_command(
    invocation: ClaudeNativeInvocation,
    argv: tuple[str, ...],
) -> ClaudeProcessResult:
    started = time.monotonic()
    environment = native_session_environment(
        executor="claude-code",
        executor_version=invocation.surface_version,
        provider="anthropic",
        markers={"CLAUDE_CODE_ENTRYPOINT": "cli"},
    )
    completed = subprocess.run(
        list(argv),
        cwd=invocation.cwd,
        env=environment,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=CLAUDE_NATIVE_TIMEOUT_SECONDS,
        check=False,
    )
    duration_ms = max(0, int((time.monotonic() - started) * 1000))
    return ClaudeProcessResult(
        completed.returncode,
        duration_ms,
        _bounded_text(completed.stdout),
        _bounded_text(completed.stderr),
    )


def run_claude_process(invocation: ClaudeNativeInvocation) -> ClaudeProcessResult:
    """Run one documented background command with private bounded output."""
    return _run_claude_command(invocation, invocation.argv)


def lookup_claude_session(invocation: ClaudeNativeInvocation) -> ClaudeProcessResult:
    return _run_claude_command(invocation, (invocation.executable, "agents", "--json"))


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
        hasattr(context, name)
        for name in ("surface_version", "requested_model", "presentation")
    )


def _native_invocation(
    context: RelayExecutionContext,
    executable: str,
    instruction: str,
) -> ClaudeNativeInvocation | None:
    launch = context.job_kind == "launch"
    session_id = context.job_id if launch else str(context.target_session_id or "")
    if not session_id.strip():
        return None
    raw_model = getattr(context, "requested_model", None) if launch else None
    return ClaudeNativeInvocation(
        executable,
        context.checkout,
        session_id,
        str(context.surface_version),
        instruction,
        resume=not launch,
        model=str(raw_model).strip() if raw_model else None,
    )


def _short_background_id(process: ClaudeProcessResult) -> str | None:
    matched = _BACKGROUND_ID_PATTERN.search(f"{process.stdout}\n{process.stderr}")
    return matched.group(1) if matched else None


def _actual_session_id(short_id: str, output: str) -> str | None:
    try:
        document = json.loads(output)
    except (TypeError, ValueError):
        return None
    if isinstance(document, dict):
        document = document.get("agents", document.get("sessions"))
    if not isinstance(document, list):
        return None
    matches = set()
    for row in document:
        if not isinstance(row, dict):
            continue
        row_id = row.get("id") or row.get("agentId") or row.get("shortId")
        if str(row_id or "") != short_id:
            continue
        try:
            matches.add(str(UUID(str(row.get("sessionId") or ""))))
        except (TypeError, ValueError, AttributeError):
            continue
    return matches.pop() if len(matches) == 1 else None


def run_claude_cli_adapter(
    context: RelayExecutionContext,
    *,
    process_runner: ClaudeProcessRunner = run_claude_process,
    session_lookup: ClaudeSessionLookup = lookup_claude_session,
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
            UUID(context.job_id)
        except (TypeError, ValueError, AttributeError):
            return _result(context, "not_created", "native_session_invalid")
        if not context.launch_attestation or attestation_handoff is None:
            return _result(context, "not_created", "attestation_handoff_unavailable")
    invocation = _native_invocation(context, executable, expected)
    if invocation is None:
        result = "not_created" if context.job_kind == "launch" else "not_found"
        return _result(context, result, "native_session_missing")
    try:
        process = process_runner(invocation)
    except Exception:  # native exceptions may contain prompts, output, or tokens
        result = "outcome_unknown" if context.job_kind == "launch" else "failed"
        return _result(context, result, "native_exception")
    if process.returncode != 0:
        result = "outcome_unknown" if context.job_kind == "launch" else "failed"
        return _result(context, result, "native_exit", process=process)
    if context.job_kind == "launch":
        short_id = _short_background_id(process)
        if short_id is None:
            return _result(context, "outcome_unknown", "identity_parse_failed")
        try:
            lookup = session_lookup(invocation)
        except Exception:  # lookup output and errors are private native material
            return _result(context, "outcome_unknown", "identity_lookup_failed")
        combined = ClaudeProcessResult(
            lookup.returncode,
            min(process.duration_ms + lookup.duration_ms, 3_600_000),
        )
        actual_id = _actual_session_id(short_id, lookup.stdout)
        if lookup.returncode != 0 or actual_id is None:
            code = (
                "identity_lookup_failed"
                if lookup.returncode
                else "identity_parse_failed"
            )
            return _result(context, "outcome_unknown", code, process=combined)
        try:
            staged = attestation_handoff(
                context.job_id,
                context.launch_attestation,
                binding_id=actual_id,
            )
        except Exception:  # the secret must never be copied into failure evidence
            staged = False
        if not staged:
            return _result(
                context,
                "outcome_unknown",
                "attestation_handoff_failed",
                native_session_id=actual_id,
                process=combined,
            )
        return _result(
            context,
            "native_created",
            "native_created",
            native_session_id=actual_id,
            process=combined,
        )
    return _result(context, "accepted", "accepted", process=process)
