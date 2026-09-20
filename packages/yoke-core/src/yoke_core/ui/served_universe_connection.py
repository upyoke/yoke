"""The control plane the view server will read, and whether it may serve it.

:func:`serving_connection` resolves the connection from
:func:`yoke_core.domain.yoke_connected_env.load_active` — the same
authority :func:`yoke_core.ui.proxy_transport.relays_to_server` consults
when it chooses a transport. Reading one authority is the point: a guard
resolving the connection some other way could permit a view whose reads
then relay somewhere else, which is the failure it exists to prevent.

The refusal itself belongs to the machine-config contract
(:mod:`yoke_contracts.machine_config.served_view_connection`), so the CLI
gate before a daemon starts and this check inside the serving process
give the same answer.
"""

from __future__ import annotations

from typing import Optional, Tuple

from yoke_contracts.machine_config.served_view_connection import (
    view_serving_refusal,
)

#: Recovery recipe for a refusal raised from inside the serving process.
#: ``yoke ui up`` pins the env it was started with into the daemon, so the
#: override reaches the child that actually opens the universe.
SERVE_COMMAND = "yoke ui up"


def serving_connection() -> Tuple[str, Optional[str]]:
    """Return ``(environment name, refusal)`` for the connection served.

    An empty environment name with no refusal is the unbound case: no
    binding selects a control plane, so the dispatcher runs in this
    process against the database it opens directly. That is the same
    status quo ``relays_to_server`` keeps, and it is what a test run and
    a config-less local universe both look like.
    """
    from yoke_core.domain import machine_config, yoke_connected_env

    try:
        env = yoke_connected_env.load_active()
    except yoke_connected_env.ConnectedEnvError as exc:
        return "", (
            "the machine's connection binding cannot be read, so this view "
            "cannot state which universe would answer its reads: "
            f"{exc}; repair it (or start over from `yoke config example`) "
            "before serving a view."
        )
    if env is None:
        return "", None
    try:
        payload = machine_config.load_config(env.binding_path)
    except Exception:  # noqa: BLE001 - the recipe degrades, the refusal does not
        payload = None
    return env.environment, view_serving_refusal(
        env.config, payload=payload, command=SERVE_COMMAND
    )


def environment_display_label(environment: str) -> Optional[str]:
    """The label naming which universe answered, for the served page.

    ``None`` leaves the runtime-identity packet on its own default: with
    no binding there is no env name to show, and inventing one would be
    the same unfounded claim the label exists to retire.
    """
    return f"local universe: {environment}" if environment else None


__all__ = [
    "SERVE_COMMAND",
    "environment_display_label",
    "serving_connection",
]
