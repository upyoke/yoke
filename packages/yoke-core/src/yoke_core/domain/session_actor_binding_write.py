"""Recording which actor this machine operates a universe as.

The write side of :mod:`yoke_core.domain.session_actor_binding`. Reading
a binding happens on every session registration; writing one happens at
the few moments that actually know the answer — universe birth, universe
import, and the operator's explicit bind command.

Writers refuse rather than record something a later reader could
not prove: a binding is only as good as the universe it names, so a
control plane that cannot state its own identity gets no binding at all.
"""

from __future__ import annotations

from typing import Any, Optional

from yoke_contracts.machine_config import runtime as machine_config
from yoke_contracts.machine_config.schema_connections import (
    MachineConfigContractError,
    with_operating_actor_binding,
)
from yoke_core.domain.session_actor_binding import _selected_env
from yoke_core.domain.universe_identity import universe_fingerprint


def persist_operating_actor(
    conn: Any,
    actor_id: int,
    *,
    env: Optional[str] = None,
    config_path: Any = None,
) -> tuple[str, str]:
    """Record *actor_id* as this machine's operating actor for a connection.

    Called by the paths that already know the answer — universe birth,
    universe import and the operator's own bind
    command — so that every later session reads an id instead of guessing
    from a login or a name. Returns ``(env, universe)`` as recorded.

    Raises :class:`MachineConfigContractError` when no env can be
    resolved, the named connection is not configured, or the universe
    cannot state its own identity — a binding whose universe is unknown
    is one the reader can never prove, so it is refused at write time
    rather than accepted and distrusted forever after.
    """
    selected = _selected_env(env, config_path)
    if not selected:
        raise MachineConfigContractError(
            "no connection env is selected, so this machine has nowhere to "
            "record an operating actor; run `yoke env use <env>` or pass an "
            "explicit env"
        )
    universe = universe_fingerprint(conn)
    if not universe:
        raise MachineConfigContractError(
            "this control plane does not answer for its own identity (a "
            "universe carries exactly one organization identity card, and "
            "this one carries none or several), so a binding recorded now "
            "could not be proven to belong to it later; bring the universe "
            "to one organization before binding an operating actor"
        )
    payload = machine_config.load_config(config_path)
    updated = with_operating_actor_binding(
        payload, selected, actor_id=int(actor_id), universe=universe
    )
    machine_config.write_config(machine_config.config_path(config_path), updated)
    return selected, universe


__all__ = ["persist_operating_actor"]
