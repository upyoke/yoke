"""How the local UI server reaches the control plane it is connected to.

The proxy used to dispatch every admitted call in its own process, which
answers correctly only when the machine holds the database. On an https
connection the process holds nothing: reads that resolve tenant-owned
configuration — artifact storage is the one that bites — decide against a
local view that does not exist and report a refusal the control plane
would not have made. So the proxy routes the way every other Yoke caller
does, keyed by the connection: relay to the server over https, dispatch
in-process on a local Postgres connection.

Identity follows the transport. In-process, the server resolves the
machine's operator itself, exactly as before. Over the relay it sends no
actor at all: the server binds the authenticated identity behind the
credential, and an actor id asserted by a caller is precisely the claim
that must never travel.
"""

from __future__ import annotations

from typing import Any, Dict, Optional


def relays_to_server() -> bool:
    """Whether this process reaches its control plane over https.

    Relaying is the new route and needs positive evidence for it: an
    active binding that names a transport this machine cannot open
    directly. Everything else — no binding at all, an unreadable one, a
    local Postgres connection — keeps dispatching in this process, which
    is what the server did before there was a choice. Failing to the
    status quo is deliberate: a test run and a local universe are both
    unbound, and neither should start relaying because a config file was
    missing.
    """
    from yoke_core.domain import db_backend, yoke_connected_env

    try:
        env = yoke_connected_env.load_active()
    except Exception:  # noqa: BLE001 - an unreadable binding is not a relay
        return False
    if env is None:
        return False
    return env.backend != db_backend.POSTGRES


def relay_call(
    *,
    function_id: str,
    target: Any,
    payload: Dict[str, Any],
    options: Optional[Dict[str, Any]] = None,
    request_id: Optional[str] = None,
) -> Any:
    """Run one admitted call on the connected server.

    Deliberately takes no actor. The relay is authenticated, and the
    server derives the acting identity from that credential; passing one
    from here would let the browser's own envelope reach the dispatcher
    as an identity claim by way of this process.
    """
    from yoke_core.api.service_client_structured_api_adapter import (
        call_dispatcher,
    )

    return call_dispatcher(
        function_id=function_id,
        target=target,
        payload=payload,
        options=options or {},
        request_id=request_id,
    )


__all__ = ["relay_call", "relays_to_server"]
