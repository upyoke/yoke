"""Idempotent actor role grants and revocations at project and org scope.

Split from :mod:`yoke_core.domain.actor_permissions`, which owns the role and
permission catalog and re-exports these writers.
"""

from __future__ import annotations

from yoke_contracts.timestamps import utc_now
from yoke_core.domain.db_helpers import instant_parameter

from typing import Any


def _catalog() -> Any:
    """The catalog module, imported late: it re-exports this module's writers."""
    from yoke_core.domain import actor_permissions

    return actor_permissions


def grant_actor_project_role(
    conn: Any,
    *,
    actor_id: int,
    project_id: int,
    role_name: str,
    granted_by_actor_id: int | None = None,
) -> None:
    """Grant ``role_name`` to ``actor_id`` in ``project_id`` idempotently."""
    from yoke_core.domain.actor_owner_protection import require_owner_change_allowed
    from yoke_core.domain.actor_role import require_human_org_role

    catalog = _catalog()
    p = catalog._p(conn)
    person = conn.execute(
        f"SELECT kind FROM actors WHERE id = {p}", (actor_id,)
    ).fetchone()
    if person and person[0] == "human":
        require_human_org_role(role_name)
    require_owner_change_allowed(
        conn,
        granted_by_actor_id,
        actor_id,
        ("project", project_id),
        "owner"
        if role_name == "owner"
        or conn.execute(
            "SELECT 1 FROM actor_project_roles ar JOIN roles r ON r.id=ar.role_id "
            f"WHERE ar.actor_id={p} AND ar.project_id={p} AND r.name='owner'",
            (actor_id, project_id),
        ).fetchone()
        else role_name,
    )
    role_id = catalog.role_id_by_name(conn, role_name)
    p = catalog._p(conn)
    conn.execute(
        "INSERT INTO actor_project_roles "
        "(actor_id, project_id, role_id, granted_at, granted_by_actor_id) "
        f"VALUES ({p}, {p}, {p}, {p}, {p}) "
        "ON CONFLICT(actor_id, project_id, role_id) DO NOTHING",
        (
            actor_id,
            project_id,
            role_id,
            instant_parameter(conn, utc_now()),
            granted_by_actor_id,
        ),
    )
    conn.commit()


def revoke_actor_project_role(
    conn: Any,
    *,
    actor_id: int,
    project_id: int,
    role_name: str,
    caller_actor_id: int,
) -> bool:
    """Remove one project role grant, returning whether a row existed.

    Absence is success: operators may safely repeat a least-privilege cutover
    after losing the previous command result.
    """
    from yoke_core.domain.actor_owner_protection import require_owner_change_allowed

    require_owner_change_allowed(
        conn,
        caller_actor_id,
        actor_id,
        ("project", project_id),
        None if role_name == "owner" else "unchanged",
    )
    catalog = _catalog()
    role_id = catalog.role_id_by_name(conn, role_name)
    p = catalog._p(conn)
    cursor = conn.execute(
        "DELETE FROM actor_project_roles "
        f"WHERE actor_id = {p} AND project_id = {p} AND role_id = {p}",
        (actor_id, project_id, role_id),
    )
    conn.commit()
    return bool(cursor.rowcount)


def grant_actor_org_role(
    conn: Any,
    *,
    actor_id: int,
    org_id: int,
    role_name: str,
    granted_by_actor_id: int | None = None,
    commit: bool = True,
) -> None:
    """Grant org ``role_name`` and commit unless ``commit=False``.

    A person's grant replaces their one role; system roles accumulate.
    Raises ``ValueError``
    for a role outside ``ORG_ROLES`` or a refused person grant
    (``actor_role.ActorRoleRefused``).
    """
    catalog = _catalog()
    if role_name not in catalog.ORG_ROLES:
        raise ValueError(
            f"role_not_grantable_at_org_scope: {role_name!r} is not one of "
            f"{', '.join(catalog.ORG_ROLES)}"
        )
    from yoke_core.domain.actor_role import record_org_grant

    from yoke_core.domain.db_savepoint import savepoint

    if (
        not commit
        and not catalog.db_backend.connection_is_postgres(conn)
        and not conn.in_transaction
    ):
        conn.execute("BEGIN")
    with savepoint(conn, "actor_org_grant", owns=commit):
        record_org_grant(
            conn,
            actor_id=actor_id,
            org_id=org_id,
            role=role_name,
            granted_by_actor_id=granted_by_actor_id,
            now=utc_now(),
        )
    if commit:
        conn.commit()


__all__ = [
    "grant_actor_org_role",
    "grant_actor_project_role",
    "revoke_actor_project_role",
]
