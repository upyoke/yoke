"""Who a freshly born local universe belongs to, and how it records that.

Birth is the moment a machine learns which actor it operates its own
universe as, so it is the moment to write that down. Everything after
reads the recorded id: no later path infers an identity from the OS
login or from a name, and this module never does either — the login only
supplies a starting NAME for a row being created, and a universe that
already carries a human keeps that one whatever it is called.
"""

from __future__ import annotations

import getpass
from typing import Callable, Optional


def _os_login_name() -> Optional[str]:
    """The OS login to name a fresh universe's human actor, or None.

    A starting name only. The identity every later session binds to is the
    actor id this birth records in the machine's operating-actor binding;
    nothing reads the login back to decide who somebody is.
    """
    try:
        return getpass.getuser() or None
    except Exception:
        return None


def _ensure_human_actor(emit: Callable[[str], None]) -> int:
    """Return the machine owner's actor id, seeding and granting org admin.

    Birth is where the machine learns who it operates this universe as, so
    it records the binding here rather than leaving every later session to
    infer it. A machine whose config cannot take the binding still gets a
    working universe; the refusal a later session reads names the one
    command that records it.
    """
    from yoke_core.domain import actors, db_helpers
    from yoke_core.domain.local_operating_actor import (
        ensure_local_operating_actor,
    )
    from yoke_core.domain.session_actor_binding_write import persist_operating_actor

    conn = db_helpers.connect()
    try:
        actor_id, seeded = ensure_local_operating_actor(
            conn, name=_os_login_name() or actors.DEFAULT_LOCAL_HUMAN_NAME
        )
        if seeded:
            emit(f"  [local-universe] seeded local human actor {actor_id}")
        try:
            env, _universe = persist_operating_actor(conn, actor_id)
            emit(
                f"  [local-universe] bound actor {actor_id} as this machine's "
                f"operator for connection {env!r}"
            )
        except Exception as exc:  # noqa: BLE001 — birth outlives a config miss
            emit(
                "  [local-universe] could not record the operating-actor "
                f"binding ({exc}); run `yoke config bind-actor --actor-id "
                f"{actor_id}` once this machine's connection is configured"
            )
        return actor_id
    finally:
        conn.close()



__all__ = ["_ensure_human_actor", "_os_login_name"]
