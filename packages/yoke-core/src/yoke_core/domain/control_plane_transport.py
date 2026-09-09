"""How local engine code reaches control-plane rows.

Two paths, in order of preference. A direct connection is primary: engine
work runs in a subprocess that has no ambient session, and a local connection
needs only machine possession. Relaying through the dispatcher is the
fallback for a control plane the client cannot open at all, which is what an
https connection is.

:func:`serving_authority` inverts that preference for the operations that
need it. Holding a database door says nothing about running the build that
database was converged for, so an operation whose result depends on the
code and the schema being one deployable pair must execute where that pair
lives.

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
    *,
    env: Optional[str] = None,
) -> dict:
    """Run one control-plane operation on the connected control plane.

    A refused relay raises, so a caller that cannot reach its state fails
    loudly rather than proceeding on a silently empty result.

    *target* takes a ``TargetRef`` for operations that address a specific
    row; the default global target suits payload-addressed operations. An
    item target may carry the raw public reference, which the dispatcher
    resolves server-side — a client with no local database can still name
    a ``PREFIX-N`` item.

    *env* names one configured connection to relay through instead of the
    active one. The transport refuses rather than falling back when that
    env resolves to no https connection, because a caller that named a
    plane meant it.
    """
    from yoke_contracts.api.function_call import TargetRef
    from yoke_core.api.service_client_structured_api_adapter import (
        call_dispatcher,
    )

    response = call_dispatcher(
        function_id=function_id,
        target=target if target is not None else TargetRef(kind="global"),
        payload=payload,
        relay_env=env,
    )
    if not response.success:
        message = (
            response.error.message if response.error is not None
            else f"{function_id} failed"
        )
        raise RuntimeError(message)
    return response.result or {}


def serving_control_plane_env() -> str:
    """The env of the build that serves this universe's control plane.

    An https connection *is* that build's front door. A direct-Postgres
    admin connection is not a plane at all — it is an owner-only door into
    one universe's database — so the plane that answers for the same
    universe is its https sibling. Returns ``""`` when neither resolves,
    which is the answer for a local universe: the process holding the
    database is also the build serving it.
    """
    try:
        from yoke_cli.transport.https import resolve_https_connection

        https = resolve_https_connection()
    except Exception:  # noqa: BLE001 - an unusable connection selects nothing
        https = None
    if https is not None:
        return str(https.env or "")
    try:
        from yoke_cli.config import machine_config
        from yoke_contracts.machine_config.schema import same_universe_https_env

        return same_universe_https_env(
            machine_config.load_config(), machine_config.active_env(),
        )
    except Exception:  # noqa: BLE001 - an unreadable config pairs with nothing
        return ""


def serving_authority(
    function_id: str,
    payload: dict,
    target: Optional[Any] = None,
) -> dict:
    """Run one operation on the build that SERVES this universe.

    Code and schema are one deployable pair, and a client can hold a
    database door while running an entirely different revision — a
    workstation driving a release runs the candidate, the database is
    still the one the deployed build converged. An operation that reads a
    column the candidate added, or a table the candidate removed, is
    correct only where that pair lives, so this routes to the serving
    plane rather than dispatching in this process.

    A universe with no https plane is served by the process holding it, so
    the relay dispatches in-process and the pair is intact either way.
    """
    return relay(
        function_id,
        payload,
        target,
        env=serving_control_plane_env() or None,
    )


__all__ = [
    "local_connection_or_none",
    "relay",
    "serving_authority",
    "serving_control_plane_env",
]
