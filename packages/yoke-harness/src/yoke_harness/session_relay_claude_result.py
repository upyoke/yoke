"""Sanitized Claude adapter results and private failure stream routing."""

from __future__ import annotations

from yoke_harness.session_relay_claude_process import ClaudeProcessResult
from yoke_harness.session_relay_native_diagnostics import classify_native_failure
from yoke_harness.session_relay_runtime import (
    RelayAdapterResult,
    RelayExecutionContext,
    RelayPrivateDiagnostic,
)
from yoke_contracts.session_control.presentation import (
    CLAUDE_LOCAL_PRESENTATION,
    CLAUDE_REMOTE_CONTROL_SETTING,
)
from yoke_contracts.session_control.launch_registration import (
    BACKGROUND_IDENTITY_MISSING_CODE,
    IDENTITY_LISTING_LAGGED_CODE,
)


def _private_process_diagnostic(
    process: ClaudeProcessResult,
    *,
    error_step: str,
    failure_class: str | None = None,
) -> RelayPrivateDiagnostic:
    stdout = process.stdout_bytes or process.stdout.encode("utf-8", errors="replace")
    stderr = process.stderr_bytes or process.stderr.encode("utf-8", errors="replace")
    return RelayPrivateDiagnostic(
        failure_class or classify_native_failure(stderr),
        error_step=error_step,
        stdout=stdout,
        stderr=stderr,
    )


def _evidence(
    context: RelayExecutionContext,
    code: str,
    process: ClaudeProcessResult | None = None,
    *,
    probe_detail: str | None = None,
) -> dict[str, object]:
    evidence: dict[str, object] = {
        "result_code": code,
        "surface": context.surface,
    }
    if probe_detail:
        evidence["probe_detail"] = probe_detail
    elif context.job_kind == "launch" and not getattr(context, "session_name", None):
        evidence["probe_detail"] = control_plane_schema_skew_detail("session_name")
    if context.presentation == CLAUDE_LOCAL_PRESENTATION:
        evidence["presentation_preference"] = CLAUDE_LOCAL_PRESENTATION
        evidence["presentation_control"] = CLAUDE_REMOTE_CONTROL_SETTING
    if process is not None:
        evidence["duration_ms"] = max(0, min(process.duration_ms, 3_600_000))
        evidence["exit_code"] = int(process.returncode)
        if process.pid is not None:
            evidence["native_launch_pid"] = process.pid
        if context.job_kind == "launch":
            evidence["native_launch_phase"] = (
                "spawn_completed_after_bound"
                if process.bound_exceeded
                else "spawn_completed"
            )
    return evidence


def control_plane_schema_skew_detail(field: str) -> str:
    """Explain a launch-contract field gap and its operator recovery."""
    return (
        f"{field} absent: control plane is behind relay; "
        "deploy control plane to converge launch contract"
    )


def build_claude_result(
    context: RelayExecutionContext,
    result_code: str,
    evidence_code: str,
    *,
    adapter_revision: str,
    native_session_id: str | None = None,
    process: ClaudeProcessResult | None = None,
    private_diagnostic: RelayPrivateDiagnostic | None = None,
    probe_detail: str | None = None,
) -> RelayAdapterResult:
    capture_identity_output = bool(
        process is not None
        and evidence_code
        in {BACKGROUND_IDENTITY_MISSING_CODE, IDENTITY_LISTING_LAGGED_CODE}
        and (
            process.stdout_bytes
            or process.stderr_bytes
            or process.stdout
            or process.stderr
        )
    )
    # A launch is retained whatever it reported. The create that succeeds is
    # the same one whose native can die minutes later having claimed nothing,
    # and by then this is the only account of how it came up.
    if (
        private_diagnostic is None
        and process is not None
        and (
            context.job_kind == "launch"
            or process.returncode != 0
            or capture_identity_output
        )
    ):
        private_diagnostic = _private_process_diagnostic(
            process,
            error_step="resume" if context.job_kind == "wake" else "launch",
            failure_class=(evidence_code if capture_identity_output else None),
        )
    return RelayAdapterResult(
        result_code,
        native_session_id=native_session_id,
        adapter_revision=adapter_revision,
        evidence=_evidence(
            context,
            evidence_code,
            process,
            probe_detail=probe_detail,
        ),
        private_diagnostic=private_diagnostic,
    )


__all__ = ["build_claude_result", "control_plane_schema_skew_detail"]
