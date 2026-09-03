"""Closed Claude CLI create and stopped-session wake routes."""

from __future__ import annotations

from functools import partial
from typing import Callable
from uuid import UUID

from yoke_harness.session_relay_claude_identity import (
    background_agent_id,
    resolve_background_session,
)
from yoke_harness.session_relay_claude_process import ClaudeProcessResult
from yoke_harness.session_relay_claude_native import (
    CLAUDE_CREATE_TIMEOUT_SECONDS as CLAUDE_CREATE_TIMEOUT_SECONDS,
    CLAUDE_CREATE_HANDOFF_RESERVE_SECONDS as CLAUDE_CREATE_HANDOFF_RESERVE_SECONDS,
    CLAUDE_NATIVE_COMMAND_TIMEOUT_SECONDS as CLAUDE_NATIVE_COMMAND_TIMEOUT_SECONDS,
    ClaudeNativeInvocation as ClaudeNativeInvocation,
    ClaudeProcessRunner,
    ClaudeSessionLookup,
    ClaudeWakeSpawner,
    ExecutableFinder,
    discover_claude_cli,
    lookup_claude_session,
    native_invocation,
    run_claude_process,
    spawn_claude_wake,
    stop_claude_background,
)
from yoke_harness.session_relay_claude_result import (
    build_claude_result,
    control_plane_schema_skew_detail,
)
from yoke_harness.session_relay_claude_transcript import (
    claude_session_transcript_exists,
)
from yoke_harness.session_relay_runtime import (
    native_instruction_targets_job,
    RelayAdapterResult,
    RelayExecutionContext,
    RelayPrivateDiagnostic,
    wake_operation,
)
from yoke_contracts.session_control.resume import RESUMED_RUNNING_RESULT
from yoke_contracts.session_control.presentation import CLAUDE_LOCAL_PRESENTATION


CLAUDE_ADAPTER_REVISION = "claude-native-v6"
CLAUDE_CLI_SURFACE = "claude-cli"
_result = partial(
    build_claude_result,
    adapter_revision=CLAUDE_ADAPTER_REVISION,
)


SurfaceVersionGate = Callable[[str, str | None, str], bool]
LaunchAttestationHandoff = Callable[..., bool]


def _contain_failed_launch(
    invocation: ClaudeNativeInvocation,
    short_id: str | None = None,
) -> None:
    """Best-effort containment before a failed create becomes retryable."""
    if short_id:
        stop_claude_background(invocation, short_id)
    try:
        from yoke_harness.session_launch_containment import contain_launch_native

        contain_launch_native(invocation.session_id, reason="create_failed")
    except Exception:
        pass


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


def _operation_authorized(
    context: RelayExecutionContext,
    operation: str,
    gate: SurfaceVersionGate | None,
) -> bool:
    if _operation_supported(context, operation, gate):
        return True
    try:
        from yoke_harness.session_relay_private_qualification import (
            private_route_qualification_allows,
        )

        return private_route_qualification_allows(context, operation=operation)
    except Exception:
        return False


def unsupported_claude_route(
    context: RelayExecutionContext,
) -> RelayAdapterResult:
    """Return the typed refusal for non-CLI Claude surfaces."""
    code = "not_created" if context.job_kind == "launch" else "unsupported_surface"
    return _result(context, code, "unsupported_surface")


def _missing_control_plane_launch_field(
    context: RelayExecutionContext,
) -> str | None:
    for name in ("surface_version", "presentation"):
        value = getattr(context, name, None)
        if not isinstance(value, str) or not value.strip():
            return name
    return None


def run_claude_cli_adapter(
    context: RelayExecutionContext,
    *,
    process_runner: ClaudeProcessRunner = run_claude_process,
    wake_spawner: ClaudeWakeSpawner = spawn_claude_wake,
    session_lookup: ClaudeSessionLookup = lookup_claude_session,
    executable_finder: ExecutableFinder | None = None,
    version_gate: SurfaceVersionGate | None = None,
    attestation_handoff: LaunchAttestationHandoff | None = None,
) -> RelayAdapterResult:
    """Create or wake exactly one Claude CLI session, failing closed."""
    if context.surface != CLAUDE_CLI_SURFACE:
        return unsupported_claude_route(context)
    if context.job_kind not in {"launch", "wake"}:
        return _result(context, "failed", "job_kind_invalid")
    if context.job_kind == "launch":
        missing_field = _missing_control_plane_launch_field(context)
        if missing_field is not None:
            return _result(
                context,
                "not_created",
                "control_plane_schema_skew",
                probe_detail=control_plane_schema_skew_detail(missing_field),
            )
    operation = "create"
    if context.job_kind == "wake":
        operation = wake_operation(
            getattr(context, "wake_mode", None), context.target_liveness
        )
        if operation is None:
            return _result(context, "failed", "wake_mode_invalid")
    if not _operation_authorized(context, operation, version_gate):
        result = "not_created" if context.job_kind == "launch" else "version_mismatch"
        return _result(context, result, "version_mismatch")
    if not native_instruction_targets_job(context):
        result = "not_created" if context.job_kind == "launch" else "failed"
        return _result(context, result, "instruction_invalid")
    executable = discover_claude_cli(executable_finder)
    if executable is None:
        result = "not_created" if context.job_kind == "launch" else "failed"
        return _result(context, result, "executable_unavailable")
    if context.job_kind == "launch":
        if context.presentation != CLAUDE_LOCAL_PRESENTATION:
            return _result(context, "not_created", "presentation_unsupported")
        try:
            UUID(context.job_id)
        except (TypeError, ValueError, AttributeError):
            return _result(context, "not_created", "native_session_invalid")
        if not context.launch_attestation or attestation_handoff is None:
            return _result(context, "not_created", "attestation_handoff_unavailable")
    elif context.presentation not in (None, CLAUDE_LOCAL_PRESENTATION):
        return _result(context, "failed", "presentation_unsupported")
    # The native is handed the sentence the control plane issued, never a
    # second one written here: an adapter that re-derives its own wording is
    # how a native reads an instruction no one attested, and how a wake
    # prompt drifts out of step with the acknowledgement the receipt waits
    # for — or, when the two builds disagree, how every wake refuses.
    invocation = native_invocation(context, executable, context.native_instruction)
    if invocation is None:
        result = "not_created" if context.job_kind == "launch" else "not_found"
        return _result(context, result, "native_session_missing")
    if operation == "message_stopped" and not claude_session_transcript_exists(
        context.checkout,
        str(context.target_session_id or ""),
    ):
        return _result(context, "failed", "transcript_missing")
    if context.job_kind == "wake":
        try:
            resumed = wake_spawner(context, invocation)
        except Exception as exc:  # native exceptions stay private on this relay
            return _result(
                context,
                "failed",
                "native_exception",
                private_diagnostic=RelayPrivateDiagnostic(
                    "native_exception",
                    error_step="resume",
                    stderr=str(exc).encode("utf-8", errors="replace"),
                ),
            )
        if resumed is None:
            return _result(context, "failed", "resume_spawn_failed")
        return RelayAdapterResult(
            RESUMED_RUNNING_RESULT,
            adapter_revision=CLAUDE_ADAPTER_REVISION,
            evidence={**resumed.evidence, "surface": context.surface},
        )
    try:
        process = process_runner(invocation)
    except Exception as exc:  # native exceptions stay private on this relay
        _contain_failed_launch(invocation)
        result = "outcome_unknown" if context.job_kind == "launch" else "failed"
        return _result(
            context,
            result,
            "native_exception",
            private_diagnostic=RelayPrivateDiagnostic(
                "native_exception",
                error_step="resume" if context.job_kind == "wake" else "launch",
                stderr=str(exc).encode("utf-8", errors="replace"),
            ),
        )
    if process.returncode != 0:
        _contain_failed_launch(invocation)
        result = "outcome_unknown" if context.job_kind == "launch" else "failed"
        return _result(
            context,
            result,
            "native_exit",
            process=process,
        )
    short_id = background_agent_id(process)
    if short_id is None:
        _contain_failed_launch(invocation)
        return _result(
            context,
            "outcome_unknown",
            "identity_parse_failed",
            process=process,
        )
    resolution = resolve_background_session(
        short_id, lambda: session_lookup(invocation)
    )
    combined = ClaudeProcessResult(
        resolution.returncode,
        min(process.duration_ms + resolution.duration_ms, 3_600_000),
        pid=process.pid,
        bound_exceeded=process.bound_exceeded,
    )
    actual_id = resolution.session_id
    if actual_id is None:
        _contain_failed_launch(invocation, short_id)
        return _result(
            context, "outcome_unknown", resolution.result_code, process=combined
        )
    try:
        staged = attestation_handoff(
            context.job_id,
            context.launch_attestation,
            binding_id=actual_id,
        )
    except Exception:  # the secret must never be copied into failure evidence
        staged = False
    if not staged:
        _contain_failed_launch(invocation, short_id)
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
