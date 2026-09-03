"""Closed Claude CLI create and stopped-session wake routes."""

from __future__ import annotations

from functools import partial
from typing import Callable
from uuid import UUID

from yoke_harness.session_relay_claude_create import immediate_native_refusal
from yoke_harness.session_relay_claude_native import (
    ClaudeNativeInvocation as ClaudeNativeInvocation,
    ClaudeNativeSpawner,
    ClaudeWakeSpawner,
    ExecutableFinder,
    discover_claude_cli,
    native_invocation,
    spawn_claude_create,
    spawn_claude_wake,
)
from yoke_harness.session_relay_claude_result import (
    build_claude_result,
    control_plane_schema_skew_detail,
)
from yoke_harness.session_relay_claude_transcript import (
    claude_session_transcript_exists,
)
from yoke_harness.session_relay_native_diagnostics import (
    MODEL_COMBO_UNSUPPORTED,
    classify_native_failure,
    model_combo_rejection_detail,
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


CLAUDE_ADAPTER_REVISION = "claude-relay-owned-process-v1"
CLAUDE_CLI_SURFACE = "claude-cli"
NATIVE_SPAWNED_CODE = "native_spawned"
_result = partial(
    build_claude_result,
    adapter_revision=CLAUDE_ADAPTER_REVISION,
)


SurfaceVersionGate = Callable[[str, str | None, str], bool]


def _contain_failed_launch(invocation: ClaudeNativeInvocation) -> None:
    """Best-effort containment before a failed create becomes retryable."""
    try:
        from yoke_harness.session_launch_containment_sweep import contain_launch_native

        contain_launch_native(str(invocation.launch_id or ""), reason="create_failed")
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


def _refuse_launch_preconditions(
    context: RelayExecutionContext,
) -> RelayAdapterResult | None:
    if context.presentation != CLAUDE_LOCAL_PRESENTATION:
        return _result(context, "not_created", "presentation_unsupported")
    try:
        UUID(context.job_id)
    except (TypeError, ValueError, AttributeError):
        return _result(context, "not_created", "native_session_invalid")
    if not context.launch_attestation:
        # The native registers itself from the attestation it inherits, so a
        # launch without one would start a session nothing could ever bind.
        return _result(context, "not_created", "launch_attestation_missing")
    return None


def _run_create(
    context: RelayExecutionContext,
    invocation: ClaudeNativeInvocation,
    create_spawner: ClaudeNativeSpawner,
) -> RelayAdapterResult:
    try:
        started = create_spawner(invocation)
    except Exception as exc:  # native exceptions stay private on this relay
        _contain_failed_launch(invocation)
        return _result(
            context,
            "outcome_unknown",
            "native_exception",
            private_diagnostic=RelayPrivateDiagnostic(
                "native_exception",
                error_step="launch",
                stderr=str(exc).encode("utf-8", errors="replace"),
            ),
        )
    if started is None:
        _contain_failed_launch(invocation)
        return _result(context, "outcome_unknown", "create_spawn_failed")
    refusal = immediate_native_refusal(started.capture_path)
    if refusal is not None and refusal.exit_code != 0:
        _contain_failed_launch(invocation)
        output = refusal.stderr + b"\n" + refusal.stdout
        detail = model_combo_rejection_detail(output)
        failure_code = classify_native_failure(output)
        return _result(
            context,
            "not_created",
            MODEL_COMBO_UNSUPPORTED if detail else "child_exited",
            native_evidence={
                **started.evidence,
                "exit_code": -1 if refusal.exit_code is None else refusal.exit_code,
            },
            private_diagnostic=RelayPrivateDiagnostic(
                failure_code,
                error_step="launch",
                stdout=refusal.stdout,
                stderr=refusal.stderr,
            ),
            probe_detail=detail,
        )
    return _result(
        context,
        "native_created",
        NATIVE_SPAWNED_CODE,
        native_session_id=invocation.session_id,
        native_evidence=started.evidence,
    )


def run_claude_cli_adapter(
    context: RelayExecutionContext,
    *,
    create_spawner: ClaudeNativeSpawner = spawn_claude_create,
    wake_spawner: ClaudeWakeSpawner = spawn_claude_wake,
    executable_finder: ExecutableFinder | None = None,
    version_gate: SurfaceVersionGate | None = None,
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
        refusal = _refuse_launch_preconditions(context)
        if refusal is not None:
            return refusal
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
    if context.job_kind == "launch":
        return _run_create(context, invocation, create_spawner)
    if operation == "message_stopped" and not claude_session_transcript_exists(
        context.checkout,
        str(context.target_session_id or ""),
    ):
        return _result(context, "failed", "transcript_missing")
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
