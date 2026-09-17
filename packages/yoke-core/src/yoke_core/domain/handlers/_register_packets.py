"""Packet-family handler registrations.

The four reads that render, check, and measure the agent-facing packets:
``packets.render.run``, ``packets.check.run``, ``packets.budget.get``, and
``packets.startup_delivery.get``. Split from :mod:`_register_qa_reads`, which
holds the qa/project reads and is at the authored-file line cap.
"""

from __future__ import annotations

from yoke_core.domain.handlers import (
    orchestration_packets as _orch_packets,
    orchestration_packet_budget as _orch_budget,
    orchestration_startup_delivery as _orch_startup_delivery,
)


def register(registry) -> None:
    registry.register(
        "packets.render.run",
        _orch_packets.handle_packets_render,
        _orch_packets.PacketsRenderRequest,
        _orch_packets.PacketsRenderResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.orchestration_packets",
        target_kinds=["global"],
        side_effects=[],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=[],
        adapter_status="live",
        claim_required_kind=None,
    )
    registry.register(
        "packets.check.run",
        _orch_packets.handle_packets_check,
        _orch_packets.PacketsCheckRequest,
        _orch_packets.PacketsCheckResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.orchestration_packets",
        target_kinds=["global"],
        side_effects=[],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=[],
        adapter_status="live",
        claim_required_kind=None,
    )
    registry.register(
        "packets.budget.get",
        _orch_budget.handle_packets_budget_get,
        _orch_budget.PacketsBudgetGetRequest,
        _orch_budget.PacketsBudgetGetResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.orchestration_packet_budget",
        target_kinds=["global"],
        side_effects=[],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=[],
        adapter_status="live",
        claim_required_kind=None,
    )
    registry.register(
        "packets.startup_delivery.get",
        _orch_startup_delivery.handle_packets_startup_delivery_get,
        _orch_startup_delivery.PacketsStartupDeliveryGetRequest,
        _orch_startup_delivery.PacketsStartupDeliveryGetResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.orchestration_startup_delivery",
        target_kinds=["global"],
        side_effects=[],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=[],
        adapter_status="live",
        claim_required_kind=None,
    )


__all__ = ["register"]
