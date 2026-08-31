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

Birth is not the only moment that has to converge this. A universe born
by an engine that predates the grant keeps operating after that engine
is upgraded in place, and nothing re-enters birth on that path — so the
first session to register on the upgraded universe converges the grant
through :func:`converge_operating_actor_grant`, which writes nothing the
moment the grant exists. Until that landed, the only writer was the
doctor fix, and the denial an agent actually hit never named it; both
the doctor check and the permission denial now render that recovery from
:data:`OPERATING_ACTOR_GRANT_REPAIR`, so there is one command to teach.
"""

from __future__ import annotations

from typing import Any, Optional

#: The one command that writes a missing machine-owner grant.
OPERATING_ACTOR_GRANT_REPAIR = "yoke doctor run --quick --fix"


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


def holds_org_admin(conn: Any, actor_id: int) -> bool:
    """True when *actor_id* holds the org ``admin`` role on this universe."""
    from yoke_core.domain import db_backend
    from yoke_core.domain.actor_permissions import ROLE_ADMIN

    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    row = conn.execute(
        "SELECT 1 FROM actor_org_roles aor JOIN roles r ON r.id = aor.role_id "
        f"WHERE aor.actor_id = {marker} AND r.name = {marker} LIMIT 1",
        (int(actor_id), ROLE_ADMIN),
    ).fetchone()
    return row is not None


def grant_tables_present(conn: Any) -> bool:
    """True when this database carries the tables the grant lives in.

    Both readers below run inside somebody else's open transaction —
    session registration before it inserts its row, a permission check
    on its way to raising. Asking a table that does not exist would
    abort that transaction, and recovering by rolling back would discard
    the caller's own uncommitted work: a minimal-schema fixture proved
    it, losing the items and sessions its test had just inserted. So the
    absence is a question asked up front, through the same existence
    probe the rest of the engine uses, and never an exception caught
    afterwards.
    """
    from yoke_core.domain.schema_common import _table_exists

    return all(
        _table_exists(conn, table)
        for table in ("actors", "actor_org_roles", "organizations", "roles")
    )


def single_owner_universe(conn: Any) -> Optional[int]:
    """The sole human actor of a single-owner universe, else ``None``.

    "Exactly one human" is the shape a machine-local universe has by
    construction, and the shape a server or hosted control plane does
    not: those carry an admin plus everyone who ever signed in. So it is
    the predicate that keeps the convergence below from handing org
    admin to a stranger on a multi-tenant control plane, and it needs
    nothing but the database in front of it — no machine config, no
    environment variable, no deployment-mode guess.
    """
    rows = conn.execute(
        "SELECT id FROM actors WHERE kind = 'human' ORDER BY id LIMIT 2"
    ).fetchall()
    return int(rows[0][0]) if len(rows) == 1 else None


def converge_operating_actor_grant(conn: Any) -> Optional[int]:
    """Grant the machine owner org admin when a local universe lacks it.

    The convergence point for an engine upgraded in place over a
    universe born before the grant existed: birth is never re-entered on
    that path, so the first session to register carries the repair. The
    settled case costs one existence probe and one indexed read, and
    writes nothing.

    Returns the actor that was granted, or ``None`` when there was
    nothing to converge — the grant is already present, the universe is
    not single-owner, or the database does not carry the grant tables at
    all (a schema-incomplete database is schema convergence's problem,
    not this function's).
    """
    if not grant_tables_present(conn):
        return None
    actor_id = single_owner_universe(conn)
    if actor_id is None or holds_org_admin(conn, actor_id):
        return None
    ensure_local_operating_actor(conn)
    return actor_id


def missing_grant_repair_detail(conn: Any, actor_id: Any) -> str:
    """The recovery clause for a denial caused by the missing grant.

    Empty for every other denial. A permission refusal on a control
    plane that holds many people is an authorization answer, and naming
    a local repair there would teach a command that cannot help; on a
    single-owner universe whose operator holds no org role it is the
    whole cause, and the agent that hit it concluded no grant surface
    existed at all, because nothing it could read said otherwise.
    """
    try:
        candidate = int(actor_id)
    except (TypeError, ValueError):
        return ""
    if not grant_tables_present(conn):
        return ""
    if single_owner_universe(conn) != candidate:
        return ""
    if holds_org_admin(conn, candidate):
        return ""
    return (
        "This universe's operating actor holds no org admin role, so every "
        "mutation its sessions attempt is denied. Repair: "
        f"`{OPERATING_ACTOR_GRANT_REPAIR}`, which grants exactly that role "
        "on this universe's own org."
    )


__all__ = [
    "OPERATING_ACTOR_GRANT_REPAIR",
    "converge_operating_actor_grant",
    "ensure_local_operating_actor",
    "grant_tables_present",
    "holds_org_admin",
    "missing_grant_repair_detail",
    "single_owner_universe",
]
