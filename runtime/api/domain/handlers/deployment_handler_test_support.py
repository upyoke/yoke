"""Request fixture for deployment handler tests."""

from __future__ import annotations

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)


def deployment_request(
    *,
    function: str,
    target: TargetRef | None = None,
    payload: dict | None = None,
    actor_id: str = "op",
) -> FunctionCallRequest:
    return FunctionCallRequest(
        function=function,
        actor=ActorContext(actor_id=actor_id, session_id="s-1"),
        target=target or TargetRef(kind="global"),
        payload=payload or {},
    )


__all__ = ["deployment_request"]
