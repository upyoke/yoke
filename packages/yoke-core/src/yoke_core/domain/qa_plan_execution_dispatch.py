"""Client-side dispatch helpers for ordered QA plan execution."""

from __future__ import annotations

from typing import Optional

from yoke_contracts.api.function_call import ActorContext, TargetRef
from yoke_core.domain.qa_plan_execution_result_state import QaPlanExecutionError


def call_plan_function(
    *,
    function_id: str,
    target: TargetRef,
    payload: dict,
    actor: ActorContext,
) -> dict:
    from yoke_core.domain.qa_composed_dispatch import call_qa_function

    response = call_qa_function(
        function_id=function_id,
        target=target,
        payload=payload,
        actor=actor,
    )
    if not response.success:
        code = response.error.code if response.error else "unknown"
        message = response.error.message if response.error else ""
        raise QaPlanExecutionError(f"{function_id} failed ({code}): {message}")
    return dict(response.result or {})


def execution_actor(actor: Optional[ActorContext]) -> ActorContext:
    if actor is not None:
        return actor
    from yoke_core.api.service_client_structured_api_adapter import build_actor

    return build_actor()


__all__ = ["call_plan_function", "execution_actor"]
