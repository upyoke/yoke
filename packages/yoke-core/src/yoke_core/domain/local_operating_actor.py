"""Establish the machine owner as the operating actor of a local universe.

A machine-local universe has exactly one person behind it, and that
person is both its user and its administrator. Two facts make that real:

* an ``actors`` row labeled with the machine's login — the identity every
  session on this machine registers under
  (:mod:`yoke_core.domain.session_actor_binding` resolves it); and
* the org ``admin`` role on the universe's single org — the authority the
  function dispatcher checks the moment a session names an actor.

Both are needed together. Seeding the actor without the grant produces a
universe whose sessions are bound and then denied on every mutation,
which is a worse failure than the unbound sessions it replaces: the
denial names a permission rather than the missing grant behind it.

Idempotent, so an existing universe gains whichever half it lacks the
next time it is verified. Server and hosted universes establish their
administrators through token bootstrap and sign-in instead, so this is
the local-universe path only.
"""

from __future__ import annotations

from typing import Any, Optional


def ensure_local_operating_actor(
    conn: Any, *, label: Optional[str] = None
) -> tuple[int, bool]:
    """Return ``(actor_id, seeded)`` for this machine's operating actor."""
    from yoke_core.domain import actors
    from yoke_core.domain.actor_permissions import (
        ROLE_ADMIN,
        grant_actor_org_role,
        seed_roles_and_permissions,
    )
    from yoke_core.domain.org_schema import seed_default_org

    row = conn.execute(
        "SELECT id FROM actors WHERE kind = 'human' ORDER BY id LIMIT 1"
    ).fetchone()
    seeded = row is None
    if row is not None:
        actor_id = int(row[0])
    else:
        actor_id = actors.seed_human_actor(conn)
        actors.set_actor_label(
            conn, actor_id, label or actors.DEFAULT_LOCAL_HUMAN_LABEL
        )
    seed_roles_and_permissions(conn)
    grant_actor_org_role(
        conn,
        actor_id=actor_id,
        org_id=seed_default_org(conn),
        role_name=ROLE_ADMIN,
        granted_by_actor_id=actor_id,
    )
    return actor_id, seeded


__all__ = ["ensure_local_operating_actor"]
