"""Handler registration for the frontier.* read surface."""

from __future__ import annotations

from yoke_core.domain.handlers import frontier_list as _fl


def register(registry) -> None:
    registry.register(
        "frontier.list", _fl.handle_frontier_list,
        _fl.FrontierListRequest, _fl.FrontierListResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.frontier_list",
        target_kinds=["global"],
        side_effects=[],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=[],
        adapter_status="live",
        claim_required_kind=None,
    )


__all__ = ["register"]
