"""QA function-call boundary onto the registered function dispatcher.

Every QA execution path — CLI case runs, plan execution, browser steps,
mission hosts — reaches its run/artifact/context functions through
:func:`call_qa_function`, which forwards to the structured-API dispatcher so
authorization, claim checks, and event emission stay in one place.

Evidence writes are the one routing exception. From a ``*-db-admin``
connection they relay to the https plane serving the same universe, because
that build owns the artifact store every reviewer reads; writing them through
the database door would land the bytes on this machine's disk.
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
    timeout_s: Optional[float] = None,
) -> FunctionCallResponse:
    """Call a registered QA function through the normal dispatcher."""
    from yoke_core.api.service_client_structured_api_adapter import (
        call_dispatcher,
    )
    from yoke_core.domain.qa_evidence_portability import (
        EVIDENCE_WRITE_FUNCTIONS,
        evidence_relay_env,
    )

    relay_env = (
        evidence_relay_env() if function_id in EVIDENCE_WRITE_FUNCTIONS else None
    )

    return call_dispatcher(
        function_id=function_id,
        target=target,
        payload=dict(payload or {}),
        actor=actor,
        timeout_s=timeout_s,
        relay_env=relay_env,
    )


__all__ = [
    "call_qa_function",
]
