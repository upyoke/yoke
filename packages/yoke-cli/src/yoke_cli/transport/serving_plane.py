"""Naming the build that serves this machine's control plane.

Client-side by construction: the answer comes from this machine's declared
connections, so it needs the CLI transport and machine config and nothing
from the engine. A supported ``yoke-cli`` install carries only contracts and
textual, and an operator command that resolved this through the engine would
fail on import before it ever reached the dispatcher.
"""

from __future__ import annotations

from yoke_contracts.machine_config.schema import (
    DB_ADMIN_ENV_SUFFIX,
    same_universe_https_env,
)


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


__all__ = ["ServingControlPlaneUnresolved", "serving_control_plane_env"]
