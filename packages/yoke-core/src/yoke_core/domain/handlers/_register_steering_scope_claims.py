"""Register the ``claims.steering_scope.*`` function family."""

from __future__ import annotations

from yoke_core.domain.handlers import claims_steering_scope as _steering
from yoke_core.domain.sessions_lifecycle_claim_events import (
    EVENT_STEERING_SCOPE_CLAIMED,
    EVENT_STEERING_SCOPE_RELEASED,
)


def register(registry) -> None:
    registry.register(
        "claims.steering_scope.acquire",
        _steering.handle_acquire,
        _steering.AcquireRequest,
        _steering.AcquireResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.claims_steering_scope",
        target_kinds=["global"],
        side_effects=["work_claims_insert"],
        emitted_event_names=[EVENT_STEERING_SCOPE_CLAIMED],
        guardrails=["no_intersecting_steering_scope_claim"],
        adapter_status="live",
        claim_required_kind=None,
    )
    registry.register(
        "claims.steering_scope.release",
        _steering.handle_release,
        _steering.ReleaseRequest,
        _steering.ReleaseResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.claims_steering_scope",
        target_kinds=["claim"],
        side_effects=["work_claims_update_released_at"],
        emitted_event_names=[EVENT_STEERING_SCOPE_RELEASED],
        guardrails=["actor_owns_claim"],
        adapter_status="live",
        claim_required_kind="self_only",
    )
    registry.register(
        "claims.steering_scope.list",
        _steering.handle_list,
        _steering.ListRequest,
        _steering.ListResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.claims_steering_scope",
        target_kinds=["global"],
        side_effects=[],
        emitted_event_names=[],
        guardrails=[],
        adapter_status="live",
        claim_required_kind=None,
    )


__all__ = ["register"]
