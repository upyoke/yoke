"""A person's one org role, owned by the engine.

Every human actor holds exactly one org role in the universe's organization.
This module is the single place that defines which roles a person may hold
and how a person's role is replaced. The Actors page, invites, and the
``actors.role.set`` function read its sets, and every org grant to a person
(``actor_permissions.grant_actor_org_role``) goes through its replace rule.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from yoke_core.domain import db_backend
from yoke_core.domain.actor_permissions import (
    ROLE_ADMIN,
    ROLE_DEPLOYMENT_CI,
    ROLE_HOSTED_SERVICE,
    ROLE_INFRASTRUCTURE_CI,
    ROLE_MIGRATION_VERIFICATION_CI,
    ROLE_OPERATOR,
    ROLE_VIEWER,
    PermissionDenied,
    role_id_by_name,
)
from yoke_core.domain.actor_state import actor_active_sql
from yoke_core.domain.control_plane_authority import resolve_control_plane_org_id

# Org roles a person may hold, most to least authority.
HUMAN_ORG_ROLES = (ROLE_ADMIN, ROLE_OPERATOR, ROLE_VIEWER)
# Roles that belong only to machine credentials, never to a person.
MACHINE_ONLY_ROLES = (
    ROLE_DEPLOYMENT_CI,
    ROLE_HOSTED_SERVICE,
    ROLE_INFRASTRUCTURE_CI,
    ROLE_MIGRATION_VERIFICATION_CI,
)


class ActorRoleRefused(ValueError):
    """A requested role change violates a named boundary."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class ActorRoleChange:
    actor_id: int
    role: str
    previous_role: str | None
    changed: bool


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def require_human_org_role(role: str) -> None:
    """Refuse a role a person may not hold, naming the reason and the set."""
    allowed = ", ".join(HUMAN_ORG_ROLES)
    if role in MACHINE_ONLY_ROLES:
        raise ActorRoleRefused(
            "machine_only_role",
            f"{role} is a machine-only role and cannot be granted to a person; "
            f"choose one of {allowed}",
        )
    if role not in HUMAN_ORG_ROLES:
        raise ActorRoleRefused(
            "role_not_assignable",
            f"{role!r} is not a person's org role; choose one of {allowed}",
        )


def resolve_member_actor(conn: Any, email: str) -> int:
    """Return the actor linked to a member email in this universe."""
    normalized = email.strip().lower()
    rows = conn.execute(
        "SELECT DISTINCT actor_id FROM actor_external_identities "
        f"WHERE LOWER(email) = {_p(conn)} ORDER BY actor_id",
        (normalized,),
    ).fetchall()
    if not rows:
        raise ActorRoleRefused(
            "member_not_linked",
            f"no actor in this universe is linked to {normalized}; the member "
            "must sign in once, then retry, or pass the ACTOR-ID instead",
        )
    if len(rows) > 1:
        ids = ", ".join(str(int(row[0])) for row in rows)
        raise ActorRoleRefused(
            "member_ambiguous",
            f"{normalized} is linked to actors {ids}; pass the ACTOR-ID instead",
        )
    return int(rows[0][0])


def org_role_of(conn: Any, actor_id: int, org_id: int) -> str | None:
    p = _p(conn)
    row = conn.execute(
        "SELECT r.name FROM actor_org_roles aor JOIN roles r ON r.id = aor.role_id "
        f"WHERE aor.actor_id = {p} AND aor.org_id = {p} ORDER BY r.name LIMIT 1",
        (actor_id, org_id),
    ).fetchone()
    return None if row is None else str(row[0])


def _other_active_human_admin(conn: Any, actor_id: int, org_id: int) -> bool:
    p = _p(conn)
    row = conn.execute(
        "SELECT 1 FROM actor_org_roles aor "
        "JOIN roles r ON r.id = aor.role_id "
        "JOIN actors other_actor ON other_actor.id = aor.actor_id "
        f"WHERE aor.org_id = {p} AND aor.actor_id <> {p} AND r.name = {p} "
        f"AND other_actor.kind = 'human' AND {actor_active_sql(conn, 'other_actor')} "
        "LIMIT 1",
        (org_id, actor_id, ROLE_ADMIN),
    ).fetchone()
    return row is not None


def replace_person_role(
    conn: Any,
    *,
    actor_id: int,
    org_id: int,
    role: str,
    granted_by_actor_id: int | None,
    now: str,
) -> str | None:
    """Make ``role`` the person's only org role; return the role it replaced.

    The caller owns the transaction. Demoting the org's last active admin is
    refused here, so no grant path can strand the org without one.
    """
    require_human_org_role(role)
    previous = org_role_of(conn, actor_id, org_id)
    if previous == role:
        return previous
    if previous == ROLE_ADMIN and not _other_active_human_admin(conn, actor_id, org_id):
        raise ActorRoleRefused(
            "last_admin",
            f"actor {actor_id} is the last active admin of the org; make "
            "another active person admin first",
        )
    p = _p(conn)
    conn.execute(
        f"DELETE FROM actor_org_roles WHERE actor_id = {p} AND org_id = {p}",
        (actor_id, org_id),
    )
    conn.execute(
        "INSERT INTO actor_org_roles "
        "(actor_id, org_id, role_id, granted_at, granted_by_actor_id) "
        f"VALUES ({p}, {p}, {p}, {p}, {p})",
        (actor_id, org_id, role_id_by_name(conn, role), now, granted_by_actor_id),
    )
    return previous


def record_org_grant(
    conn: Any,
    *,
    actor_id: int,
    org_id: int,
    role: str,
    granted_by_actor_id: int | None,
    now: str,
) -> None:
    """Write one org grant; the caller owns the transaction.

    A person's grant replaces their one org role; a system actor's org roles
    accumulate idempotently.
    """
    p = _p(conn)
    row = conn.execute(
        f"SELECT kind FROM actors WHERE id = {p}", (actor_id,)
    ).fetchone()
    if row is not None and row[0] == "human":
        replace_person_role(
            conn,
            actor_id=actor_id,
            org_id=org_id,
            role=role,
            granted_by_actor_id=granted_by_actor_id,
            now=now,
        )
        return
    conn.execute(
        "INSERT INTO actor_org_roles "
        "(actor_id, org_id, role_id, granted_at, granted_by_actor_id) "
        f"VALUES ({p}, {p}, {p}, {p}, {p}) "
        "ON CONFLICT(actor_id, org_id, role_id) DO NOTHING",
        (actor_id, org_id, role_id_by_name(conn, role), now, granted_by_actor_id),
    )


def set_actor_org_role(
    conn: Any,
    *,
    actor_id: int,
    role: str,
    caller_actor_id: int,
    now: str,
) -> ActorRoleChange:
    """Set a person's one org role in a single locked transaction.

    The organization and actor rows are locked before the last-admin check,
    the same order ``set_actor_enabled`` takes, so a concurrent disable or
    demotion cannot strand the org without an admin.
    """
    require_human_org_role(role)
    p = _p(conn)
    lock = " FOR UPDATE" if db_backend.connection_is_postgres(conn) else ""
    try:
        conn.execute(f"SELECT id FROM organizations ORDER BY id{lock}").fetchall()
        try:
            org_id = resolve_control_plane_org_id(conn)
        except PermissionDenied as exc:
            raise ActorRoleRefused("org_ambiguous", str(exc)) from exc
        row = conn.execute(
            f"SELECT kind FROM actors WHERE id = {p}{lock}", (actor_id,)
        ).fetchone()
        if row is None:
            raise ActorRoleRefused(
                "actor_not_found", f"actor {actor_id} does not exist; refresh Actors"
            )
        if row[0] != "human":
            raise ActorRoleRefused(
                "actor_not_human",
                f"actor {actor_id} is a system actor; its roles come from the "
                "credential that provisioned it, not from a person's org role",
            )
        previous = replace_person_role(
            conn,
            actor_id=actor_id,
            org_id=org_id,
            role=role,
            granted_by_actor_id=caller_actor_id,
            now=now,
        )
        conn.commit()
        return ActorRoleChange(actor_id, role, previous, changed=previous != role)
    except Exception:
        conn.rollback()
        raise
