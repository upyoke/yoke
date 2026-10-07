"""Who a freshly born local universe belongs to, and how it records that.

Birth is the moment a machine learns which actor it operates its own
universe as, so it is the moment to write that down. Everything after
reads the recorded id: no later path infers an identity from a name. The
installer's name, asked by ``yoke setup``, only names the row being created,
and a universe that already carries a human keeps that one whatever it is
called.
"""

from __future__ import annotations

from typing import Callable, Optional


def require_admin_name(value: Optional[str]) -> str:
    """The validated installer's name a new universe needs, or a named refusal."""
    from yoke_contracts import first_admin_name as admin

    try:
        return admin.validate_admin_name(value)
    except admin.AdminNameError as exc:
        raise RuntimeError(
            f"{admin.ADMIN_NAME_MISSING}: creating a local universe needs your "
            f"name for its first admin ({exc}). Recovery: rerun `yoke setup` "
            "and enter your name (`--admin-name NAME` when non-interactive), or "
            "run `yoke init --local --admin-name NAME`"
        ) from None


def _ensure_human_actor(
    emit: Callable[[str], None], admin_name: Optional[str] = None
) -> int:
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
        if actors.sole_human_actor_id(conn, oldest=True) is None:
            admin_name = require_admin_name(admin_name)
        actor_id, seeded = ensure_local_operating_actor(conn, name=admin_name)
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


__all__ = ["_ensure_human_actor", "record_operating_actor", "require_admin_name"]
