"""How local engine code reaches control-plane rows.

Two paths, in order of preference. A direct connection is primary: engine
work runs in a subprocess that has no ambient session, and a local connection
needs only machine possession. Relaying through the dispatcher is the
fallback for a control plane the client cannot open at all, which is what an
https connection is.

Any operation that runs client-side and touches control-plane state belongs
on this pair. Opening a bare connection instead fails outright on an
https-connected machine — on the transport most sessions actually use.
"""

from __future__ import annotations

from typing import Any, Callable, Optional


def local_connection_or_none(connect: Callable[[], Any]) -> Optional[Any]:
    """Open a direct connection, or report that there is no local authority."""
    try:
        return connect()
    except Exception:  # noqa: BLE001 - no local authority is the relay's cue
        return None


def relay(function_id: str, payload: dict) -> dict:
    """Run one control-plane operation on the connected control plane.

    A refused relay raises, so a caller that cannot reach its state fails
    loudly rather than proceeding on a silently empty result.
    """
    from yoke_contracts.api.function_call import TargetRef
    from yoke_core.api.service_client_structured_api_adapter import (
        call_dispatcher,
    )

    response = call_dispatcher(
        function_id=function_id,
        target=TargetRef(kind="global"),
        payload=payload,
    )
    if not response.success:
        message = (
            response.error.message if response.error is not None
            else f"{function_id} failed"
        )
        raise RuntimeError(message)
    return response.result or {}


__all__ = ["local_connection_or_none", "relay"]
