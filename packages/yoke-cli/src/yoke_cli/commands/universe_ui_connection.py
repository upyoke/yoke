"""Which connection may be served as a local universe view, and by what.

The operator-facing ``yoke ui`` commands gate on this before starting a
daemon, so the refusal arrives in the terminal that asked. It is a
preflight, not the enforcement: the view server refuses the same
connection itself, which is what covers a launch agent brought back at
login against a binding that became hosted or prod-flagged since it was
registered, and any caller that reaches the server without this command.
Both read one contract rule so they cannot disagree.

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
from yoke_contracts.machine_config.schema import MachineConfigContractError
from yoke_contracts.machine_config.served_view_connection import (
    view_serving_refusal,
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

    Which connection modes may be served is the contract's answer
    (:func:`view_serving_refusal`), so this preflight and the re-check
    inside the serving process cannot drift apart. What belongs here is
    only what the operator running the command can act on: a machine
    config that is missing or unusable before any connection resolves.
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
    try:
        payload = machine_config.load_config()
    except (machine_config.MachineConfigError, MachineConfigContractError):
        # Only the recipe's env inventory degrades; a connection that may
        # not be served is still refused, and for the same reason.
        payload = None
    env_label = str(connection.get("env") or "<env>")
    return env_label, view_serving_refusal(connection, payload=payload)


__all__ = [
    "UniverseUiError",
    "converge_universe_schema",
    "servable_connection",
    "ui_server",
]
