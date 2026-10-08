"""Handler registrations for the events.* read family."""

from __future__ import annotations

from yoke_core.domain.handlers import events_emit as _emit
from yoke_core.domain.handlers import events_reads as _ev
from yoke_core.domain.handlers import performance_reads as _perf


def register(registry) -> None:
    """Register the events read handlers via the given registry module."""
    for verb, handler, request, response in (
        (
            "aggregate",
            _perf.handle_aggregate,
            _perf.PerformanceRequest,
            _perf.PerformanceResponse,
        ),
        (
            "detail",
            _perf.handle_detail,
            _perf.PerformanceDetailRequest,
            _perf.PerformanceDetailResponse,
        ),
    ):
        registry.register(
            f"events.performance.{verb}",
            handler,
            request,
            response,
            stability="stable",
            owner_module="yoke_core.domain.handlers.performance_reads",
            target_kinds=["global"],
            side_effects=[],
            emitted_event_names=["YokeFunctionCalled"],
            guardrails=["actor_project_visibility"],
            adapter_status="live",
            claim_required_kind=None,
            ambient_session_required=False,
            minimum_serving_version="next-release",
        )
    for entry in _emit.REGISTRATIONS:
        registry.register(**entry)
    registry.register(
        "events.query.run",
        _ev.handle_events_query,
        _ev.EventsQueryRequest,
        _ev.EventsQueryResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.events_reads",
        target_kinds=["global", "item"],
        side_effects=[],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=[],
        adapter_status="live",
        claim_required_kind=None,
    )
    registry.register(
        "events.tail.run",
        _ev.handle_events_tail,
        _ev.EventsTailRequest,
        _ev.EventsTailResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.events_reads",
        target_kinds=["global"],
        side_effects=[],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=[],
        adapter_status="live",
        claim_required_kind=None,
    )
    registry.register(
        "events.count.run",
        _ev.handle_events_count,
        _ev.EventsCountRequest,
        _ev.EventsCountResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.events_reads",
        target_kinds=["global", "item"],
        side_effects=[],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=[],
        adapter_status="live",
        claim_required_kind=None,
    )
    registry.register(
        "events.anomalies.run",
        _ev.handle_events_anomalies,
        _ev.EventsAnomaliesRequest,
        _ev.EventsAnomaliesResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.events_reads",
        target_kinds=["global", "item"],
        side_effects=[],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=[],
        adapter_status="live",
        claim_required_kind=None,
    )
