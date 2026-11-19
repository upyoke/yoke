"""The recovery an org member reads when their org role cannot do something.

An org-scoped denial that names only the permission sends the reader to the
wrong place: an org ``operator`` refused ``project.create`` read that their
API token lacked rights, when the cause is their role. When the denied actor
holds a role on the org, this clause names that role, the human roles that
would allow the operation, and who can change it. Every other denial (no org
role, or a permission no human role carries) gets no clause.
"""

from __future__ import annotations

from typing import Any

from yoke_core.domain.actor_effective_roles import HUMAN_ROLES
from yoke_core.domain.actor_permissions import (
    PERM_PROJECT_CREATE,
    ROLE_ADMIN,
    SERVICE_ONLY_PERMISSIONS,
    _p,
)

_ACTION_PHRASES = {PERM_PROJECT_CREATE: "creating a project"}


def _held_org_roles(conn: Any, *, actor_id: int, org_id: int) -> list[str]:
    p = _p(conn)
    rows = conn.execute(
        "SELECT r.name FROM actor_org_roles aor JOIN roles r ON r.id = aor.role_id "
        f"WHERE aor.actor_id = {p} AND aor.org_id = {p} ORDER BY r.name",
        (actor_id, org_id),
    ).fetchall()
    return [str(row[0]) for row in rows]


def _granting_human_roles(conn: Any, permission_key: str) -> list[str]:
    """Human roles that allow ``permission_key`` at org scope, highest first."""
    p = _p(conn)
    rows = conn.execute(
        "SELECT r.name FROM roles r "
        "JOIN role_permissions rp ON rp.role_id = r.id "
        "JOIN permissions perm ON perm.id = rp.permission_id "
        f"WHERE perm.key = {p}",
        (permission_key,),
    ).fetchall()
    # Org admin is all-access by construction, whatever role_permissions says.
    granting = {str(row[0]) for row in rows} | {ROLE_ADMIN}
    return [role for role in HUMAN_ROLES if role in granting]


def _actor_label(conn: Any, actor_id: int) -> str:
    p = _p(conn)
    row = conn.execute(f"SELECT name FROM actors WHERE id = {p}", (actor_id,)).fetchone()
    name = str(row[0]).strip() if row and row[0] is not None else ""
    return name or f"actor {actor_id}"


def org_role_recovery_detail(
    conn: Any, *, actor_id: int, org_id: int, permission_key: str
) -> str:
    """Name the denied member's org role and the roles that would allow it.

    Empty when the actor holds no role on the org or no human role can carry
    the permission, so those denials keep their own wording.
    """
    if permission_key in SERVICE_ONLY_PERMISSIONS:
        return ""
    held = _held_org_roles(conn, actor_id=actor_id, org_id=org_id)
    if not held:
        return ""
    granting = _granting_human_roles(conn, permission_key)
    # Suggest the least powerful role that allows it.
    suggested = granting[-1]
    action = _ACTION_PHRASES.get(permission_key, repr(permission_key))
    plural = "roles" if len(held) > 1 else "role"
    return (
        f"{_actor_label(conn, actor_id)} holds org {plural} {', '.join(held)}; "
        f"{action} needs org role {' or '.join(granting)}. Ask an org owner or "
        "admin to do it for you, or to change your role with "
        f"`yoke actors role set --member EMAIL --role {suggested}`."
    )


__all__ = ["org_role_recovery_detail"]
