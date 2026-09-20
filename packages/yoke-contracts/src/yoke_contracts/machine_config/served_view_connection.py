"""Which machine-config connection may back a served local-universe view.

A view server answers from whichever control plane its own dispatcher
selects, and that selection is connection-keyed: on an https connection
every read relays to the hosted control plane. A view served over one
therefore renders a universe nobody pointed it at, and neither the page
nor a screenshot of it says so — the server is real, the page is real,
only the provenance is wrong.

So this is an allowlist, not a denylist: only a non-prod local-postgres
connection may be served, and every other mode refuses by name. An
unrecognized transport fails closed until it is deliberately admitted.

The rule lives in the contract because both callers need the identical
answer: the CLI gates before starting a view daemon, and the engine's
view server re-checks in the process that actually serves.
"""

from __future__ import annotations

from typing import Any, Mapping, Optional

from yoke_contracts.machine_config.schema_connections import (
    ENV_OVERRIDE,
    connection_is_prod,
    local_postgres_envs,
)
from yoke_contracts.machine_config.schema_transport import (
    POSTGRES_TRANSPORTS,
    TRANSPORT_HTTPS,
)

#: The command the recovery recipe names. Callers reached through a
#: different entrypoint pass their own so the recipe stays runnable.
VIEW_SERVE_COMMAND = "yoke ui up"


def view_serving_refusal(
    connection: Mapping[str, Any],
    *,
    payload: Optional[Mapping[str, Any]] = None,
    command: str = VIEW_SERVE_COMMAND,
) -> Optional[str]:
    """Return why ``connection`` may not be served as a view, or ``None``.

    ``payload`` is the whole machine config when the caller has it, so the
    recipe can name the local-postgres envs this machine actually has
    instead of a placeholder.
    """
    env_label = str(connection.get("env") or "<env>")
    transport = str(connection.get("transport") or "").strip()
    if transport in POSTGRES_TRANSPORTS and not connection_is_prod(connection):
        return None
    if transport == TRANSPORT_HTTPS:
        return (
            f"the connection {env_label!r} is https-transport, so this "
            "process reaches its control plane by relaying: a view served "
            "over it would answer every read from the hosted universe "
            "while naming none of it on the page. A view serves the "
            "machine-local universe only, and the hosted/self-host web "
            f"surfaces arrive with the platform. {_switch_recipe(payload, command)}"
        )
    if transport in POSTGRES_TRANSPORTS:
        return (
            f"the connection {env_label!r} is a prod-flagged Postgres "
            "connection: direct prod authority is operator-only, so it is "
            f"not served as a view. {_switch_recipe(payload, command)}"
        )
    return (
        f"the connection {env_label!r} (transport "
        f"{transport or '<unset>'!r}) is not a mode a view can be served "
        "over: only a non-prod local-postgres connection is served, because "
        "it is the only one this process reads directly. "
        f"{_switch_recipe(payload, command)}"
    )


def _switch_recipe(
    payload: Optional[Mapping[str, Any]],
    command: str,
) -> str:
    """The one-line way to serve a database this machine holds."""
    candidates = local_postgres_envs(payload)
    if not candidates:
        return (
            "No local-postgres env is configured on this machine; "
            "`yoke init --local` creates a local universe to view."
        )
    return (
        f"Serve one this machine holds: {ENV_OVERRIDE}={candidates[0]} "
        f"{command} (configured local-postgres envs: "
        f"{', '.join(candidates)})."
    )


__all__ = ["VIEW_SERVE_COMMAND", "view_serving_refusal"]
