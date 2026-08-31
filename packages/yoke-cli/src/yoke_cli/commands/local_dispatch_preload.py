"""What has to be true before the CLI dispatches in-process through the engine.

Two preconditions, in order. The engine's handler registry has to be loaded,
which is transport- and connection-keyed rather than command-keyed. And the
universe about to be served has to carry the schema the loaded build reads,
which for a machine-local universe has no other moment to happen in: a hosted
container converges on boot, while here the serving process is this command.

Both are done once per process, at the single gate every dispatching adapter
already calls, so an upgraded engine cannot reach a database it has not first
brought up to itself.
"""

from __future__ import annotations

import importlib
import sys

_convergence_attempted = False


def ensure_handlers_loaded() -> None:
    """Register the engine's handlers when in-process dispatch is sanctioned.

    The gate is transport-keyed on the active connection: an https
    connection relays to the server, so no local handlers load; a
    prod-flagged postgres connection is operator-only by doctrine, so
    this pre-load declines it; any other local-postgres connection is
    a local universe whose in-process dispatch is the product path, so
    the engine's handler registry loads. A machine without the engine
    importable degrades to a no-op — the dispatcher then fails closed
    with ``local_postgres_core_unavailable``.
    """
    try:
        from yoke_cli.transport.https import resolve_https_connection

        if resolve_https_connection() is not None:
            return
    except Exception:
        return
    if _active_connection_is_prod_postgres():
        return
    try:
        register = importlib.import_module(
            "yoke_core.domain.handlers.__init_register__"
        )
    except ImportError:
        return
    register.register_all_handlers()
    _converge_local_universe()


def _active_connection_is_prod_postgres() -> bool:
    """True when the active connection is prod-flagged local postgres.

    Prod postgres stays operator-only: the sanctioned admin surfaces
    drive it explicitly, so this client-side pre-load declines to
    register in-process handlers against it.
    """
    try:
        from yoke_cli.config import machine_config
        from yoke_contracts.machine_config.schema import (
            connection_is_prod,
            POSTGRES_TRANSPORTS,
        )

        connection = machine_config.active_connection()
    except Exception:
        return False
    transport = str(connection.get("transport") or "").strip()
    return transport in POSTGRES_TRANSPORTS and connection_is_prod(connection)


def _converge_local_universe() -> None:
    """Bring this machine's own universe up to the engine, once per process.

    Fail-loud rather than fail-open: a process that could not converge the
    database it is about to serve stops here with the named reason and the
    recovery, because continuing is how an upgraded engine ends up reading
    columns the universe never received.
    """
    global _convergence_attempted
    if _convergence_attempted:
        return
    _convergence_attempted = True
    from yoke_cli import engine_upgrade_convergence

    try:
        engine_upgrade_convergence.converge_for_serving(
            emit=lambda line: print(line, file=sys.stderr),
        )
    except engine_upgrade_convergence.LocalUniverseConvergenceError as exc:
        print(f"yoke: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


__all__ = ["ensure_handlers_loaded"]
