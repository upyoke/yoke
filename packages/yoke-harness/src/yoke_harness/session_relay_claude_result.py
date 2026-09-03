"""Sanitized Claude adapter results and private failure stream routing."""

from __future__ import annotations

from typing import Mapping

from yoke_harness.session_relay_runtime import (
    RelayAdapterResult,
    RelayExecutionContext,
    RelayPrivateDiagnostic,
)
from yoke_contracts.session_control.presentation import (
    CLAUDE_LOCAL_PRESENTATION,
    CLAUDE_REMOTE_CONTROL_SETTING,
)


def _evidence(
    context: RelayExecutionContext,
    code: str,
    native_evidence: Mapping[str, object] | None = None,
    *,
    probe_detail: str | None = None,
) -> dict[str, object]:
    # The spawn's own facts go down first and the adapter's verdict over them:
    # a running spawn describes itself as running, and only the adapter knows
    # whether that spawn is this job's outcome.
    evidence: dict[str, object] = dict(native_evidence or {})
    evidence.update({"result_code": code, "surface": context.surface})
    if probe_detail:
        evidence["probe_detail"] = probe_detail
    elif context.job_kind == "launch" and not getattr(context, "session_name", None):
        evidence["probe_detail"] = control_plane_schema_skew_detail("session_name")
    if context.presentation == CLAUDE_LOCAL_PRESENTATION:
        evidence["presentation_preference"] = CLAUDE_LOCAL_PRESENTATION
        evidence["presentation_control"] = CLAUDE_REMOTE_CONTROL_SETTING
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
    native_evidence: Mapping[str, object] | None = None,
    private_diagnostic: RelayPrivateDiagnostic | None = None,
    probe_detail: str | None = None,
) -> RelayAdapterResult:
    return RelayAdapterResult(
        result_code,
        native_session_id=native_session_id,
        adapter_revision=adapter_revision,
        evidence=_evidence(
            context,
            evidence_code,
            native_evidence,
            probe_detail=probe_detail,
        ),
        private_diagnostic=private_diagnostic,
    )


__all__ = ["build_claude_result", "control_plane_schema_skew_detail"]
