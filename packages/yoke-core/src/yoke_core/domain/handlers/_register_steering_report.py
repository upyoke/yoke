"""Register the ``steering.report.*`` function family."""

from __future__ import annotations

from yoke_core.domain.handlers import steering_report as _report


def register(registry) -> None:
    registry.register(
        "steering.report.get",
        _report.handle_get,
        _report.SteeringReportGetRequest,
        _report.SteeringReportGetResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.steering_report",
        target_kinds=["global"],
        side_effects=[],
        emitted_event_names=[],
        guardrails=["caller_holds_project_steering_claim"],
        adapter_status="live",
        claim_required_kind=None,
    )


__all__ = ["register"]
