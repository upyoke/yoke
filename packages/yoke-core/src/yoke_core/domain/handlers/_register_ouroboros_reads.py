"""Handler registrations for the ouroboros.entry.* read family."""
from __future__ import annotations

from yoke_core.domain.handlers import ouroboros_reads as _our
from yoke_core.domain.handlers import ouroboros_writes as _writes


def register(registry) -> None:
    """Register the ouroboros entry readers via the given registry module."""
    for entry in _writes.REGISTRATIONS:
        registry.register(**entry)
    registry.register(
        "ouroboros.entry.list", _our.handle_ouroboros_entry_list,
        _our.OuroborosEntryListRequest, _our.OuroborosEntryListResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.ouroboros_reads",
        target_kinds=["global"], side_effects=[],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=[], adapter_status="live", claim_required_kind=None,
    )
    registry.register(
        "ouroboros.entry.get", _our.handle_ouroboros_entry_get,
        _our.OuroborosEntryGetRequest, _our.OuroborosEntryGetResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.ouroboros_reads",
        target_kinds=["global"], side_effects=[],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=[], adapter_status="live", claim_required_kind=None,
    )
    registry.register(
        "ouroboros.field_note.list", _our.handle_ouroboros_entry_list,
        _our.OuroborosEntryListRequest, _our.OuroborosEntryListResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.ouroboros_reads",
        target_kinds=["global"], side_effects=[],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=[], adapter_status="live", claim_required_kind=None,
    )
    registry.register(
        "ouroboros.field_note.get", _our.handle_ouroboros_entry_get,
        _our.OuroborosEntryGetRequest, _our.OuroborosEntryGetResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.ouroboros_reads",
        target_kinds=["global"], side_effects=[],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=[], adapter_status="live", claim_required_kind=None,
    )
