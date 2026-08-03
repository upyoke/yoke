"""How local engine code reaches control-plane rows.

Two paths, in order of preference. A direct connection is primary: engine
work runs in a subprocess that has no ambient session, and a local connection
needs only machine possession. Relaying through the dispatcher is the
fallback for a control plane the client cannot open at all, which is what an
https connection is.

Any operation that runs client-side and touches control-plane state belongs
on this pair. Opening a bare connection instead fails outright on an
https-connected machine — on the transport most sessions actually use.

Enforced rather than advised: the client entrypoint marks its execution
context, and the connection factory refuses a direct connect under that mark.
See :mod:`yoke_contracts.control_plane_locality` for the marker, the named
exception for code that means to open a local database, and the static check
that keeps the factory unbypassable.
"""

from __future__ import annotations

from typing import Any, Callable, Optional

from yoke_contracts.control_plane_locality import local_authority_exempt


def local_connection_or_none(connect: Callable[[], Any]) -> Optional[Any]:
    """Open a direct connection, or report that there is no local authority.

    Runs under :func:`local_authority_exempt` because attempting the direct
    connection IS this function's job: a refusal here would answer the
    question the attempt is asking. So the attempt runs for real, and any
    failure means the same thing — no local authority — and returns None so
    the caller relays.
    """
    try:
        with local_authority_exempt():
            return connect()
    except Exception:  # noqa: BLE001 - no local authority is the relay's cue
        return None


def relay(
    function_id: str,
    payload: dict,
    target: Optional[Any] = None,
) -> dict:
    """Run one control-plane operation on the connected control plane.

    A refused relay raises, so a caller that cannot reach its state fails
    loudly rather than proceeding on a silently empty result.

    *target* takes a ``TargetRef`` for operations that address a specific
    row; the default global target suits payload-addressed operations. An
    item target may carry the raw public reference, which the dispatcher
    resolves server-side — a client with no local database can still name
    a ``PREFIX-N`` item.
    """
    from yoke_contracts.api.function_call import TargetRef
    from yoke_core.api.service_client_structured_api_adapter import (
        call_dispatcher,
    )

    response = call_dispatcher(
        function_id=function_id,
        target=target if target is not None else TargetRef(kind="global"),
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
