"""The ``yoke config bind-actor`` writer: which actor this machine operates as.

Sibling of :mod:`yoke_cli.commands.adapters.config_write`. It lives apart
because it is the one machine-config writer that has to reach the control
plane before it writes: the binding it records names an actor AND the
universe that actor belongs to, and only the connected universe can state
its own identity.
"""

from __future__ import annotations

import argparse
import json
from importlib import import_module
from typing import Dict, List

from yoke_cli.commands._helpers import (
    attach_field_note_footer,
    parse_or_usage_error,
)
from yoke_cli.config import machine_config
from yoke_cli.config import writer


BIND_ACTOR_USAGE = (
    "yoke config bind-actor [--actor-id N] [--config PATH]"
)


USAGE_BY_FUNCTION_ID: Dict[str, str] = {"config.bind_actor.run": BIND_ACTOR_USAGE}


def config_bind_actor(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke config bind-actor",
        description=(
            "Record which actor this machine operates the selected universe "
            "as. Sessions bind that id at registration instead of guessing "
            "from an OS login or a name, so renaming somebody or two people "
            "sharing a name can never move the identity. The binding is per "
            "connection because it is per universe: the same person is a "
            "different actor id in every control plane. Defaults to the "
            "active connection; select another with the global env flag "
            "(e.g. `yoke --env prod config bind-actor --actor-id 4`). "
            "Omit --actor-id on a universe with exactly one human actor and "
            "that actor is recorded; with several, pass the id explicitly "
            "(list them with `yoke db read \"SELECT id, kind, name FROM "
            "actors\"`)."
        ),
    )
    parser.add_argument("--actor-id", dest="actor_id", type=int, default=None)
    parser.add_argument("--config", dest="config_path", default=None)
    attach_field_note_footer(parser)
    parsed = parse_or_usage_error(parser, args, BIND_ACTOR_USAGE)
    if parsed is None:
        return 2
    return _run(lambda: _bind_actor(parsed.actor_id, parsed.config_path))


def _bind_actor(actor_id, config_path) -> dict:
    """Record the binding against the universe the selected connection reaches."""
    # The engine ships beside this client but the active connection decides
    # whether it runs, so the reach is dynamic and registered in the
    # classified authority-import roster.
    db_helpers = import_module("yoke_core.domain.db_helpers")
    transport = import_module("yoke_core.domain.control_plane_transport")
    binding = import_module("yoke_core.domain.session_actor_binding")
    binding_write = import_module("yoke_core.domain.session_actor_binding_write")
    explicit_actor_binding = binding.explicit_actor_binding
    converge_operating_actor_binding = binding_write.converge_operating_actor_binding
    persist_operating_actor = binding_write.persist_operating_actor

    conn = transport.local_connection_or_none(db_helpers.connect)
    if conn is None:
        raise writer.MachineConfigWriteError(
            "the selected connection reaches its control plane over https, "
            "where a verified bearer token names your actor; there is no "
            "machine-local binding to record for it"
        )
    try:
        if actor_id is None:
            converged = converge_operating_actor_binding(
                conn, config_path=config_path
            )
            if converged is None:
                raise writer.MachineConfigWriteError(
                    "this universe does not carry exactly one human actor, so "
                    "which one operates this machine is a question only you "
                    "can answer. Pass --actor-id (list the candidates with "
                    '`yoke db read "SELECT id, kind, name FROM actors"`)'
                )
            actor_id = converged
        resolved = explicit_actor_binding(conn, actor_id)
        if not resolved.bound:
            raise writer.MachineConfigWriteError(resolved.detail)
        env, universe = persist_operating_actor(
            conn, int(actor_id), config_path=config_path
        )
        return {"env": env, "actor_id": int(actor_id), "universe": universe}
    finally:
        conn.close()


def _run(operation) -> int:
    import sys

    try:
        result = operation()
    except (writer.MachineConfigWriteError, machine_config.MachineConfigError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2))
    return 0


__all__ = ["BIND_ACTOR_USAGE", "USAGE_BY_FUNCTION_ID", "config_bind_actor"]
