"""Register the ``steering.backstop.*`` function family."""

from __future__ import annotations

from yoke_core.domain.handlers import steering_backstop as _backstop
from yoke_core.domain.steering_launch_backstop import (
    EVENT_STEERING_BACKSTOP_EVALUATED,
)


def register(registry) -> None:
    registry.register(
        "steering.backstop.evaluate",
        _backstop.handle_evaluate,
        _backstop.BackstopEvaluateRequest,
        _backstop.BackstopEvaluateResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.steering_backstop",
        target_kinds=["global"],
        side_effects=["session_launches_insert", "session_messages_insert"],
        emitted_event_names=[EVENT_STEERING_BACKSTOP_EVALUATED],
        guardrails=[
            "caller_holds_project_steering_claim",
            "steering_backstop_worker_budget",
        ],
        adapter_status="live",
        claim_required_kind=None,
    )


__all__ = ["register"]
