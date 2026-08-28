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


def _private_process_diagnostic(
    process: ClaudeProcessResult,
    *,
    error_step: str,
) -> RelayPrivateDiagnostic:
    stdout = process.stdout_bytes or process.stdout.encode("utf-8", errors="replace")
    stderr = process.stderr_bytes or process.stderr.encode("utf-8", errors="replace")
    return RelayPrivateDiagnostic(
        classify_native_failure(stderr),
        error_step=error_step,
        stdout=stdout,
        stderr=stderr,
    )


def _evidence(
    context: RelayExecutionContext,
    code: str,
    process: ClaudeProcessResult | None = None,
) -> dict[str, object]:
    evidence: dict[str, object] = {
        "result_code": code,
        "surface": context.surface,
    }
    if context.presentation == CLAUDE_LOCAL_PRESENTATION:
        evidence["presentation_preference"] = CLAUDE_LOCAL_PRESENTATION
        evidence["presentation_control"] = CLAUDE_REMOTE_CONTROL_SETTING
    if process is not None:
        evidence["duration_ms"] = max(0, min(process.duration_ms, 3_600_000))
        evidence["exit_code"] = int(process.returncode)
    return evidence


def build_claude_result(
    context: RelayExecutionContext,
    result_code: str,
    evidence_code: str,
    *,
    adapter_revision: str,
    native_session_id: str | None = None,
    process: ClaudeProcessResult | None = None,
    private_diagnostic: RelayPrivateDiagnostic | None = None,
) -> RelayAdapterResult:
    if private_diagnostic is None and process is not None and process.returncode != 0:
        private_diagnostic = _private_process_diagnostic(
            process,
            error_step="resume" if context.job_kind == "wake" else "launch",
        )
    return RelayAdapterResult(
        result_code,
        native_session_id=native_session_id,
        adapter_revision=adapter_revision,
        evidence=_evidence(context, evidence_code, process),
        private_diagnostic=private_diagnostic,
    )


__all__ = ["build_claude_result"]
