"""QA function-call boundary onto the registered function dispatcher.

Every QA execution path — CLI case runs, plan execution, browser steps,
mission hosts — reaches its run/artifact/context functions through
:func:`call_qa_function`, which forwards to the structured-API dispatcher so
authorization, claim checks, and event emission stay in one place.
"""

from __future__ import annotations

from typing import Any, Optional

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallResponse,
    TargetRef,
)


def call_qa_function(
    *,
    function_id: str,
    target: TargetRef,
    payload: Optional[dict[str, Any]] = None,
    actor: Optional[ActorContext] = None,
) -> FunctionCallResponse:
    """Call a registered QA function through the normal dispatcher."""
    from yoke_core.api.service_client_structured_api_adapter import (
        call_dispatcher,
    )

    return call_dispatcher(
        function_id=function_id,
        target=target,
        payload=dict(payload or {}),
        actor=actor,
    )


__all__ = [
    "call_qa_function",
]
