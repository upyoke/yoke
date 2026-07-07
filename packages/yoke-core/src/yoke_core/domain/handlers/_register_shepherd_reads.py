"""Handler registrations for the shepherd dependency family."""
from __future__ import annotations

from yoke_core.domain.handlers import shepherd_dependency_writes as _shw
from yoke_core.domain.handlers import shepherd_reads as _shr
from yoke_core.domain.handlers import shepherd_verdict_writes as _svw


def register(registry) -> None:
    """Register shepherd dependency handlers via the given registry module."""
    registry.register(
        "shepherd.dependency_list.run", _shr.handle_shepherd_dependency_list,
        _shr.ShepherdDependencyListRequest,
        _shr.ShepherdDependencyListResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.shepherd_reads",
        target_kinds=["item"], side_effects=[],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=[], adapter_status="live", claim_required_kind=None,
    )
    registry.register(
        "shepherd.dependency_add.run",
        _shw.handle_shepherd_dependency_add,
        _shw.ShepherdDependencyAddRequest,
        _shw.ShepherdDependencyAddResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.shepherd_dependency_writes",
        target_kinds=["item"],
        side_effects=["item_dependencies_insert"],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=["authored_rationale_required"],
        adapter_status="live",
        claim_required_kind=None,
    )
    registry.register(
        "shepherd.dependency_update.run",
        _shw.handle_shepherd_dependency_update,
        _shw.ShepherdDependencyUpdateRequest,
        _shw.ShepherdDependencyUpdateResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.shepherd_dependency_writes",
        target_kinds=["item"],
        side_effects=["item_dependencies_update"],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=["existing_edge_must_match"],
        adapter_status="live",
        claim_required_kind=None,
    )
    registry.register(
        "shepherd.dependency_remove.run",
        _shw.handle_shepherd_dependency_remove,
        _shw.ShepherdDependencyRemoveRequest,
        _shw.ShepherdDependencyRemoveResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.shepherd_dependency_writes",
        target_kinds=["item"],
        side_effects=["item_dependencies_delete"],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=["existing_edge_must_match"],
        adapter_status="live",
        claim_required_kind=None,
    )
    registry.register(
        "shepherd.verdict.run",
        _svw.handle_shepherd_verdict,
        _svw.ShepherdVerdictRequest,
        _svw.ShepherdVerdictResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.shepherd_verdict_writes",
        target_kinds=["item"],
        side_effects=["shepherd_verdicts_insert"],
        emitted_event_names=["YokeFunctionCalled", "VerdictRendered"],
        guardrails=[],
        adapter_status="live",
        claim_required_kind=None,
    )
    registry.register(
        "shepherd.caveat_disposition.run",
        _svw.handle_shepherd_caveat_disposition,
        _svw.ShepherdCaveatDispositionRequest,
        _svw.ShepherdCaveatDispositionResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.shepherd_verdict_writes",
        target_kinds=["item"],
        side_effects=["caveat_dispositions_upsert"],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=["valid_disposition_required"],
        adapter_status="live",
        claim_required_kind=None,
    )
