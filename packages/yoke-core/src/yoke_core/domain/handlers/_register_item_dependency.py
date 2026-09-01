"""Handler registrations for the items dependency family."""
from __future__ import annotations

from yoke_core.domain.handlers import item_dependency_reads as _idr
from yoke_core.domain.handlers import item_dependency_writes as _idw


def register(registry) -> None:
    """Register item-dependency handlers via the given registry module."""
    registry.register(
        "items.dependency.list", _idr.handle_item_dependency_list,
        _idr.ItemDependencyListRequest,
        _idr.ItemDependencyListResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.item_dependency_reads",
        target_kinds=["item"], side_effects=[],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=[], adapter_status="live", claim_required_kind=None,
    )
    registry.register(
        "items.dependency.add",
        _idw.handle_item_dependency_add,
        _idw.ItemDependencyAddRequest,
        _idw.ItemDependencyAddResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.item_dependency_writes",
        target_kinds=["item"],
        side_effects=["item_dependencies_insert"],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=["authored_rationale_required"],
        adapter_status="live",
        claim_required_kind=None,
    )
    registry.register(
        "items.dependency.update",
        _idw.handle_item_dependency_update,
        _idw.ItemDependencyUpdateRequest,
        _idw.ItemDependencyUpdateResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.item_dependency_writes",
        target_kinds=["item"],
        side_effects=["item_dependencies_update"],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=["existing_edge_must_match"],
        adapter_status="live",
        claim_required_kind=None,
    )
    registry.register(
        "items.dependency.remove",
        _idw.handle_item_dependency_remove,
        _idw.ItemDependencyRemoveRequest,
        _idw.ItemDependencyRemoveResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.item_dependency_writes",
        target_kinds=["item"],
        side_effects=["item_dependencies_delete"],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=["existing_edge_must_match"],
        adapter_status="live",
        claim_required_kind=None,
    )
