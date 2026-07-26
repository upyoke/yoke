"""Self-contained registration hook for item screen read contracts."""

from __future__ import annotations

from yoke_core.domain.handlers import item_page_reads as _reads


def register(registry) -> None:
    registry.register(
        "items.overview.list",
        _reads.handle_items_overview_list,
        _reads.ItemsOverviewListRequest,
        _reads.ItemsOverviewListResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.item_page_reads",
        target_kinds=["global"],
        side_effects=[],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=[],
        adapter_status="live",
        claim_required_kind=None,
    )
    registry.register(
        "items.detail.get",
        _reads.handle_item_detail_get,
        _reads.ItemDetailGetRequest,
        _reads.ItemDetailGetResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.item_page_reads",
        target_kinds=["item"],
        side_effects=[],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=[],
        adapter_status="live",
        claim_required_kind=None,
    )


__all__ = ["register"]
