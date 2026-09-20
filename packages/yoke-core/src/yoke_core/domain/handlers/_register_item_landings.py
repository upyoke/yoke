"""Register the append-only item landing history.

``item_landings.record`` is ``adapter_status='internal'`` merge glue with the
same session-optional, claim-free posture as the merge receipt it is written
beside: the merge subprocess may resolve no ambient harness session, and the
item claim and merge lock are enforced upstream by the merge boundary.

``item_landings.list`` ships a CLI adapter because "which landing is this
item answerable for, and did it ship" is a question operators and agents ask
directly — it is the audit the single-valued item columns could not answer.
"""

from __future__ import annotations

from yoke_core.domain.handlers import item_landings_ops as _ops

_MODULE = "yoke_core.domain.handlers.item_landings_ops"


def register(registry) -> None:
    registry.register(
        "item_landings.record",
        _ops.handle_record_item_landing,
        _ops.RecordItemLandingRequest,
        _ops.RecordItemLandingResponse,
        stability="stable",
        owner_module=_MODULE,
        target_kinds=["item"],
        side_effects=["item_landing_write"],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=[],
        adapter_status="internal",
        claim_required_kind=None,
        ambient_session_required=False,
        minimum_serving_version="next-release",
    )
    registry.register(
        "item_landings.list",
        _ops.handle_list_item_landings,
        _ops.ListItemLandingsRequest,
        _ops.ListItemLandingsResponse,
        stability="stable",
        owner_module=_MODULE,
        target_kinds=["item"],
        side_effects=[],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=[],
        adapter_status="live",
        claim_required_kind=None,
        ambient_session_required=False,
        minimum_serving_version="next-release",
    )


__all__ = ["register"]
