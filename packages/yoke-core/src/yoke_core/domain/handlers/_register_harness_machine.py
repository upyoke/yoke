"""Function registry entries for harness machine reports."""

from __future__ import annotations

from yoke_core.domain.handlers import harness_machine_report as _handlers


def register(registry) -> None:
    registry.register(
        "harness.machine_report.upsert",
        _handlers.handle_harness_machine_report_upsert,
        _handlers.HarnessMachineReportUpsertRequest,
        _handlers.HarnessMachineReportUpsertResponse,
        stability="stable",
        owner_module=__name__,
        target_kinds=["global"],
        side_effects=["harness_machine_reports_upsert"],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=["actor_session_bound"],
        adapter_status="live",
        claim_required_kind=None,
        ambient_session_required=True,
    )


__all__ = ["register"]
