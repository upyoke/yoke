"""Client-side dispatch helpers for ordered QA plan execution."""

from __future__ import annotations

from typing import Optional

from yoke_contracts.api.function_call import ActorContext, TargetRef


def call_plan_function(
    *,
    function_id: str,
    target: TargetRef,
    payload: dict,
    actor: ActorContext,
) -> dict:
    from yoke_core.domain.qa_plan_execution_checkin import deliver_plan_function

    return deliver_plan_function(
        function_id=function_id, target=target, payload=payload, actor=actor
    )


def execution_actor(actor: Optional[ActorContext]) -> ActorContext:
    if actor is not None:
        return actor
    from yoke_contracts.runtime_ports.structured_dispatch import get_structured_dispatch
    build_actor = get_structured_dispatch().build_actor

    return build_actor()


__all__ = ["call_plan_function", "execution_actor"]
