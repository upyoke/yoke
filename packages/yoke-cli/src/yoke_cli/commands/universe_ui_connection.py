"""Which connection may be served as a local universe view, and by what.

Both halves of ``yoke ui`` need this: the operator-facing commands gate
on it before starting a daemon, and the serving child re-checks it in
the process that actually opens the universe. The check belongs to the
process that serves, not only to the command that asked — a launch agent
brought back at login has to refuse a connection that became hosted or
prod-flagged since it was registered.

The engine imports here are dynamic on purpose: the client packages hold
no static import authority over the engine, and local mode is the one
lane where a product install *runs* it (same rule as ``yoke init
--local``).
"""

from __future__ import annotations

import importlib
from typing import Optional, Tuple

from yoke_cli.config import machine_config
from yoke_cli.config.local_universe_setup import ENGINE_MISSING_MESSAGE
from yoke_contracts.machine_config.schema import (
    MachineConfigContractError,
    POSTGRES_TRANSPORTS,
    TRANSPORT_HTTPS,
    connection_is_prod,
)

class UniverseUiError(RuntimeError):
    """The UI server could not be started for the active connection."""


def ui_server():
    try:
        return importlib.import_module("yoke_core.ui.server")
    except ModuleNotFoundError as exc:
        raise UniverseUiError(ENGINE_MISSING_MESSAGE) from exc


def converge_universe_schema() -> None:
    """Converge the local universe's schema before serving it.

    The UI server is a server booting against this universe, and every
    boot is a schema-reconciliation point: a universe born before a
    newer additive table would otherwise answer reads with undefined-
    relation errors until some other boot converges it. Same fail-hard
    contract as the API server — a UI over a half-converged universe
    would lie about what exists.
    """
    try:
        entrypoint = importlib.import_module(
            "yoke_core.api.server_entrypoint",
        )
    except ModuleNotFoundError as exc:
        raise UniverseUiError(ENGINE_MISSING_MESSAGE) from exc
    entrypoint.ensure_core_schema()


def servable_connection() -> Tuple[str, Optional[str]]:
    """Return ``(env name, refusal)`` for the connection the UI would serve.

    Allowlist, not denylist: only a non-prod local-postgres connection is
    served. Every other mode — https, prod-flagged Postgres, or any
    transport this adapter does not recognize — refuses in mode language,
    so new connection modes fail closed until deliberately admitted.
    """
    config_file = machine_config.config_path()
    try:
        connection = machine_config.active_connection()
    except (machine_config.MachineConfigError, MachineConfigContractError) as exc:
        if config_file.is_file():
            return "", (
                f"the machine config at {config_file} cannot be used: "
                f"{exc}; repair it (or start over from "
                "`yoke config example`) before `yoke ui` can serve"
            )
        return "", (
            "no active connection is configured on this machine; "
            "`yoke init --local` creates a local universe to view"
        )
    env_label = str(connection.get("env") or "<env>")
    transport = str(connection.get("transport") or "").strip()
    if transport in POSTGRES_TRANSPORTS and not connection_is_prod(connection):
        return env_label, None
    if transport == TRANSPORT_HTTPS:
        return env_label, (
            f"the active connection {env_label!r} is https-transport "
            "(hosted/self-host mode): `yoke ui` serves the machine-local "
            "universe only, and the hosted/self-host web surfaces arrive "
            "with the platform. To view a machine-local universe, switch "
            "to its env (`yoke env use local`) or create one "
            "(`yoke init --local`)."
        )
    if transport in POSTGRES_TRANSPORTS:
        return env_label, (
            f"the active connection {env_label!r} is a prod-flagged "
            "Postgres connection: direct prod authority is operator-only, "
            "so `yoke ui` refuses to serve it."
        )
    return env_label, (
        f"the active connection {env_label!r} (transport "
        f"{transport or '<unset>'!r}) is not a mode `yoke ui` recognizes: "
        "only a non-prod local-postgres connection serves the "
        "machine-local universe. Switch to one (`yoke env use <env>`) or "
        "create one (`yoke init --local`)."
    )


__all__ = [
    "UniverseUiError",
    "converge_universe_schema",
    "servable_connection",
    "ui_server",
]
