"""Recording which actor this machine operates a universe as.

The write side of :mod:`yoke_core.domain.session_actor_binding`. Reading
a binding happens on every session registration; writing one happens at
the few moments that actually know the answer — universe birth, universe
import, the operator's own bind command, and the doctor repair for a
single-owner universe that predates the binding.

Both writers refuse rather than record something a later reader could
not prove: a binding is only as good as the universe it names, so a
control plane that cannot state its own identity gets no binding at all.
"""

from __future__ import annotations

from typing import Any, Optional

from yoke_contracts.machine_config import runtime as machine_config
from yoke_contracts.machine_config.schema_connections import (
    MachineConfigContractError,
    operating_actor_binding,
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
    universe import, the doctor repair, and the operator's own bind
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


def converge_operating_actor_binding(
    conn: Any,
    *,
    env: Optional[str] = None,
    config_path: Any = None,
) -> Optional[int]:
    """Record the binding a single-owner universe leaves in no doubt.

    The one-time conversion for a machine whose universe predates the
    binding: exactly one human actor means there is nothing to choose
    between, so the id is recorded once and read by id forever after.
    Returns the actor recorded, or ``None`` when there was nothing to
    converge — a binding already exists, the universe carries several
    humans (the operator says which), or no env is selected.

    Deliberately not reached from :func:`resolve_operating_actor`. A
    conversion that ran on every resolution would be a standing fallback,
    and a standing fallback silently re-answers the identity question
    every time the recorded answer stops matching — which is exactly the
    moment somebody needs to be told.
    """
    from yoke_core.domain.actors import sole_human_actor_id

    selected = _selected_env(env, config_path)
    if not selected:
        return None
    try:
        payload = machine_config.load_config(config_path)
    except Exception:  # noqa: BLE001 — an unreadable config converges nothing
        return None
    existing, _universe = operating_actor_binding(payload, selected)
    if existing is not None:
        return None
    actor_id = sole_human_actor_id(conn)
    if actor_id is None:
        return None
    persist_operating_actor(conn, actor_id, env=selected, config_path=config_path)
    return actor_id


__all__ = [
    "converge_operating_actor_binding",
    "persist_operating_actor",
]
