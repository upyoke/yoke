"""Collapse every person to one org role and retire invites no person can hold.

A person holds exactly one org role: admin, operator, or viewer. Universes
written before that rule may carry a person with several org roles (for
example admin beside operator) or with a machine-only role. Each person keeps
their strongest person role in each org and loses every other org grant; a
person holding only machine roles keeps none. A pending invite whose role a
person cannot hold is revoked, so accepting it can no longer fail.

The role names are written out here rather than imported: this entry is
permanent history and must keep meaning what it meant when it was authored.
"""

from __future__ import annotations

from typing import Any

from yoke_core.domain.db_backend import connection_is_postgres
from yoke_core.domain.migration_serving_version import NEXT_RELEASE
from yoke_core.domain.schema_common import _table_exists

MINIMUM_SERVING_VERSION = NEXT_RELEASE

# Strongest first.
PERSON_ORG_ROLES = ("admin", "operator", "viewer")


def _marker(conn: Any) -> str:
    return "%s" if connection_is_postgres(conn) else "?"


def _person_grants(conn: Any) -> dict[tuple[int, int], list[tuple[int, str]]]:
    if not _table_exists(conn, "actor_org_roles"):
        return {}
    rows = conn.execute(
        "SELECT aor.actor_id, aor.org_id, aor.role_id, r.name "
        "FROM actor_org_roles aor "
        "JOIN roles r ON r.id = aor.role_id "
        "JOIN actors a ON a.id = aor.actor_id "
        "WHERE a.kind = 'human' ORDER BY aor.actor_id, aor.org_id, aor.role_id"
    ).fetchall()
    grants: dict[tuple[int, int], list[tuple[int, str]]] = {}
    for actor_id, org_id, role_id, name in rows:
        grants.setdefault((int(actor_id), int(org_id)), []).append(
            (int(role_id), str(name))
        )
    return grants


def _keep(roles: list[tuple[int, str]]) -> int | None:
    for wanted in PERSON_ORG_ROLES:
        for role_id, name in roles:
            if name == wanted:
                return role_id
    return None


def _invalid_pending_invites(conn: Any) -> list[int]:
    if not _table_exists(conn, "actor_invites"):
        return []
    p = _marker(conn)
    marks = ", ".join(p for _ in PERSON_ORG_ROLES)
    rows = conn.execute(
        "SELECT i.id FROM actor_invites i JOIN roles r ON r.id = i.role_id "
        f"WHERE i.status = 'pending' AND r.name NOT IN ({marks}) ORDER BY i.id",
        PERSON_ORG_ROLES,
    ).fetchall()
    return [int(row[0]) for row in rows]


def apply(conn: Any) -> None:
    p = _marker(conn)
    for (actor_id, org_id), roles in _person_grants(conn).items():
        keep = _keep(roles)
        for role_id, _name in roles:
            if role_id != keep:
                conn.execute(
                    "DELETE FROM actor_org_roles "
                    f"WHERE actor_id = {p} AND org_id = {p} AND role_id = {p}",
                    (actor_id, org_id, role_id),
                )
    for invite_id in _invalid_pending_invites(conn):
        conn.execute(
            f"UPDATE actor_invites SET status = 'revoked' WHERE id = {p}",
            (invite_id,),
        )


def invariants(conn: Any) -> None:
    for (actor_id, org_id), roles in _person_grants(conn).items():
        names = [name for _role_id, name in roles]
        if len(names) > 1 or names[0] not in PERSON_ORG_ROLES:
            raise AssertionError(
                f"person_org_roles_not_collapsed: actor {actor_id} holds "
                f"{', '.join(names)} in org {org_id}. Recovery: rehearse the "
                "one-org-role-per-person migration."
            )
    remaining = _invalid_pending_invites(conn)
    if remaining:
        raise AssertionError(
            "invalid_invite_roles_pending: invites "
            f"{', '.join(str(i) for i in remaining)}. Recovery: rehearse the "
            "one-org-role-per-person migration."
        )
