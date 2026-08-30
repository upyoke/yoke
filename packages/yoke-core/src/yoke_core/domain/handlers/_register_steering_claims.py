"""Register the ``claims.steering.*`` function family."""

from __future__ import annotations

from yoke_core.domain.handlers import claims_steering as _steering
from yoke_core.domain.sessions_lifecycle_claim_events import (
    EVENT_STEERING_CLAIMED,
    EVENT_STEERING_RELEASED,
)


def register(registry) -> None:
    registry.register(
        "claims.steering.acquire",
        _steering.handle_acquire,
        _steering.AcquireRequest,
        _steering.AcquireResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.claims_steering",
        target_kinds=["global"],
        side_effects=["work_claims_insert", "strategy_doc_claims_insert_or_pair"],
        emitted_event_names=[EVENT_STEERING_CLAIMED],
        guardrails=[
            "one_steering_claim_per_project",
            "atomic_strategy_document_pair",
        ],
        adapter_status="live",
        claim_required_kind=None,
    )
    registry.register(
        "claims.steering.release",
        _steering.handle_release,
        _steering.ReleaseRequest,
        _steering.ReleaseResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.claims_steering",
        target_kinds=["claim"],
        side_effects=[
            "work_claims_update_released_at",
            "paired_strategy_doc_claim_update_released_at",
        ],
        emitted_event_names=[EVENT_STEERING_RELEASED],
        guardrails=["actor_owns_claim", "paired_strategy_document_release"],
        adapter_status="live",
        claim_required_kind="self_only",
    )
    registry.register(
        "claims.steering.list",
        _steering.handle_list,
        _steering.ListRequest,
        _steering.ListResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.claims_steering",
        target_kinds=["global"],
        side_effects=[],
        emitted_event_names=[],
        guardrails=[],
        adapter_status="live",
        claim_required_kind=None,
    )


__all__ = ["register"]
