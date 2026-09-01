"""Handler registrations for shepherd Architect/Boss writes."""
from __future__ import annotations

from yoke_core.domain.handlers import shepherd_verdict_writes as _svw


def register(registry) -> None:
    """Register shepherd verdict handlers via the given registry module."""
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
