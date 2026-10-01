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

    The client records this returned identity after writing the local
    connection. Before that write, a fresh machine has no connection to bind.
    """
    from yoke_core.domain import actors, db_helpers
    from yoke_core.domain.local_operating_actor import (
        ensure_local_operating_actor,
    )

    conn = db_helpers.connect()
    try:
        actor_id, seeded = ensure_local_operating_actor(
            conn, name=_os_login_name() or actors.DEFAULT_LOCAL_HUMAN_NAME
        )
        if seeded:
            emit(f"  [local-universe] seeded local human actor {actor_id}")
        return actor_id
    finally:
        conn.close()


def record_operating_actor(actor_id, *, dsn, env, config_path=None):
    """Persist birth's actor against its own universe and configured connection."""
    from yoke_core.domain import db_helpers
    from yoke_core.domain.local_universe import pinned_authority
    from yoke_core.domain.session_actor_binding_write import persist_operating_actor

    with pinned_authority(dsn):
        conn = db_helpers.connect()
        try:
            return persist_operating_actor(
                conn, actor_id, env=env, config_path=config_path
            )
        finally:
            conn.close()


__all__ = ["_ensure_human_actor", "_os_login_name", "record_operating_actor"]
