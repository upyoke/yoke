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
            response.error.message
            if response.error is not None
            else f"{function_id} failed"
        )
        raise RuntimeError(message)
    return response.result or {}


class ServingControlPlaneUnresolved(RuntimeError):
    """This machine cannot name the build that serves its control plane.

    Distinct from a local universe, which has a real answer: itself. This
    is raised where an answer is owed and missing, because the failure it
    replaces is silent — falling back to "no plane" runs the operation on
    whatever revision the caller happens to be, against a database that
    belongs to a different one.
    """


def serving_control_plane_env() -> str:
    """The env of the build that serves this universe's control plane.

    An https connection *is* that build's front door. A direct-Postgres
    admin connection is not a plane at all — it is an owner-only door into
    one universe's database — so the plane that answers for the same
    universe is its https sibling.

    Returns ``""`` for exactly one situation: a local universe, where the
    process holding the database is also the build serving it. An admin
    connection whose https sibling is absent is a machine that owes an
    answer it cannot give, and raises :class:`ServingControlPlaneUnresolved`
    rather than reporting the local universe's answer for a hosted one.
    """
    from yoke_contracts.machine_config.schema import (
        DB_ADMIN_ENV_SUFFIX,
        same_universe_https_env,
    )

    try:
        from yoke_cli.transport.https import resolve_https_connection

        https = resolve_https_connection()
    except Exception as exc:  # noqa: BLE001 - a broken plane is not no plane
        raise ServingControlPlaneUnresolved(
            "the connected https control plane could not be resolved, so the "
            f"build serving it cannot be named: {exc}. Repair the connection "
            "(`yoke connection set <env> --api-url ...`) or check "
            "`yoke env list`"
        ) from exc
    if https is not None:
        return str(https.env or "")

    try:
        from yoke_cli.config import machine_config

        config = machine_config.load_config()
        active = str(machine_config.active_env() or "")
    except Exception as exc:  # noqa: BLE001 - an unreadable config answers nothing
        raise ServingControlPlaneUnresolved(
            "this machine's connection configuration could not be read, so "
            f"the build serving its control plane cannot be named: {exc}. "
            "Check `yoke env list`"
        ) from exc

    sibling = same_universe_https_env(config, active)
    if sibling:
        return sibling
    if active.endswith(DB_ADMIN_ENV_SUFFIX):
        raise ServingControlPlaneUnresolved(
            f"env {active!r} is the database door for a universe whose https "
            "plane is not configured on this machine, so the build serving "
            "that database cannot be named. Configure it with "
            f"`yoke connection set {active[: -len(DB_ADMIN_ENV_SUFFIX)]} "
            "--api-url ...`, or check `yoke env list`"
        )
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
    the relay dispatches in-process and the pair is intact either way. A
    machine that cannot name its serving plane raises rather than taking
    that path, because "no plane" and "the plane is unreachable" are
    different answers and only the first one is safe to run here.
    """
    return relay(
        function_id,
        payload,
        target,
        env=serving_control_plane_env() or None,
    )


__all__ = [
    "ServingControlPlaneUnresolved",
    "local_connection_or_none",
    "relay",
    "serving_authority",
    "serving_control_plane_env",
]
