"""Permission/authorization decisions for cloud-runtime auth.

Split from :mod:`yoke_core.domain.actor_permissions` (which owns the
role/permission catalog, seed, and grants) to keep each module under the
authored-file line cap. The public decision functions are re-exported from
``actor_permissions`` for backward compatibility — import them from there.
"""

from __future__ import annotations

from typing import Any

from yoke_core.domain.actor_permissions import (
    ORG_SCOPED_PERMISSIONS,
    PermissionDecision,
    PermissionDenied,
    ROLE_ADMIN,
    ROLE_OWNER,
    _p,
)


def _org_scope_label(conn: Any, org_id: int) -> str:
    """Render the org part of a denial as ``'NAME' (id N)``, or ``N`` as fallback.

    The caller prefixes ``org ``, so this returns only the inner label.
    ``organizations.name`` is always populated (``NOT NULL``), so the named form
    is the normal case; the id-only fallback covers a missing row (a deleted or
    not-yet-committed org) so the error never raises while reporting a denial.
    """
    p = _p(conn)
    row = conn.execute(
        f"SELECT name FROM organizations WHERE id = {p}", (org_id,)
    ).fetchone()
    name = str(row[0]) if row and row[0] is not None else None
    return f"{name!r} (id {org_id})" if name else f"{org_id}"


def _project_scope_label(conn: Any, project_id: int) -> str:
    """Render a project as ``'NAME' (slug, id N)`` for an error, or ``project N``.

    ``projects.name`` and ``projects.slug`` are both ``NOT NULL``; the id-only
    fallback covers a missing row so reporting a denial never raises.
    """
    p = _p(conn)
    row = conn.execute(
        f"SELECT name, slug FROM projects WHERE id = {p}", (project_id,)
    ).fetchone()
    if not row or row[0] is None:
        return f"project {project_id}"
    name, slug = str(row[0]), str(row[1])
    return f"{name!r} ({slug}, id {project_id})"


def _holds_org_admin(conn: Any, *, project_id: int, actor_id: int) -> bool:
    """True if the actor holds the all-access org ``admin`` role on the project's owning org."""
    p = _p(conn)
    row = conn.execute(
        "SELECT 1 FROM projects pr "
        "JOIN actor_org_roles aor ON aor.org_id = pr.org_id "
        "JOIN roles r ON r.id = aor.role_id "
        f"WHERE pr.id = {p} AND aor.actor_id = {p} AND r.name = {p} LIMIT 1",
        (project_id, actor_id, ROLE_ADMIN),
    ).fetchone()
    return row is not None


def _holds_project_owner(conn: Any, *, project_id: int, actor_id: int) -> bool:
    """True if the actor holds the ``owner`` role directly on ``project_id``."""
    p = _p(conn)
    row = conn.execute(
        "SELECT 1 FROM actor_project_roles apr "
        "JOIN roles r ON r.id = apr.role_id "
        f"WHERE apr.actor_id = {p} AND apr.project_id = {p} AND r.name = {p} LIMIT 1",
        (actor_id, project_id, ROLE_OWNER),
    ).fetchone()
    return row is not None


def permission_decision(
    conn: Any,
    *,
    actor_id: int,
    project_id: int,
    permission_key: str,
) -> PermissionDecision:
    """Authorize ``permission_key`` for ``actor_id`` against ``project_id``.

    Two all-access wildcards short-circuit ahead of the explicit
    ``role_permissions`` lookup, so the powerful roles are correct *by
    construction* and cannot be locked out by catalog drift:

    * the org ``admin`` role on the project's owning org carries every
      permission (the root identity); and
    * a project ``owner`` carries every *project-grantable* permission on its
      own project (org-scoped permissions are never carried by a project role).

    Otherwise the decision allows when an explicitly-granted org or project role
    carries the permission, exactly as before.
    """
    # Wildcard 1 — org admin (all-access), drift-proof: the admin role is defined
    # as every permission, so we never consult role_permissions for it.
    if _holds_org_admin(conn, project_id=project_id, actor_id=actor_id):
        return PermissionDecision(
            actor_id=actor_id,
            project_id=project_id,
            permission_key=permission_key,
            allowed=True,
            role_names=(ROLE_ADMIN,),
        )
    # Wildcard 2 — project owner, limited to project-grantable permissions
    # (org-scoped permissions like org.admin / project.create are never a
    # project role's to grant, so a project owner can never self-escalate to them).
    if (
        permission_key not in ORG_SCOPED_PERMISSIONS
        and _holds_project_owner(conn, project_id=project_id, actor_id=actor_id)
    ):
        return PermissionDecision(
            actor_id=actor_id,
            project_id=project_id,
            permission_key=permission_key,
            allowed=True,
            role_names=(ROLE_OWNER,),
        )
    p = _p(conn)
    # Org scope: roles the actor holds on the project's owning org.
    org_rows = conn.execute(
        "SELECT r.name "
        "FROM projects pr "
        "JOIN actor_org_roles aor ON aor.org_id = pr.org_id "
        "JOIN roles r ON r.id = aor.role_id "
        "JOIN role_permissions rp ON rp.role_id = r.id "
        "JOIN permissions perm ON perm.id = rp.permission_id "
        f"WHERE pr.id = {p} AND aor.actor_id = {p} AND perm.key = {p} "
        "ORDER BY r.name",
        (project_id, actor_id, permission_key),
    ).fetchall()
    # Project scope: roles granted directly on the project.
    proj_rows = conn.execute(
        "SELECT r.name "
        "FROM actor_project_roles apr "
        "JOIN roles r ON r.id = apr.role_id "
        "JOIN role_permissions rp ON rp.role_id = r.id "
        "JOIN permissions perm ON perm.id = rp.permission_id "
        f"WHERE apr.actor_id = {p} AND apr.project_id = {p} "
        f"AND perm.key = {p} "
        "ORDER BY r.name",
        (actor_id, project_id, permission_key),
    ).fetchall()
    names = {str(row[0]) for row in org_rows} | {str(row[0]) for row in proj_rows}
    roles = tuple(sorted(names))
    return PermissionDecision(
        actor_id=actor_id,
        project_id=project_id,
        permission_key=permission_key,
        allowed=bool(roles),
        role_names=roles,
    )


def require_permission(
    conn: Any,
    *,
    actor_id: int,
    project_id: int,
    permission_key: str,
) -> PermissionDecision:
    """Return decision when allowed; raise :class:`PermissionDenied` otherwise."""
    decision = permission_decision(
        conn,
        actor_id=actor_id,
        project_id=project_id,
        permission_key=permission_key,
    )
    if not decision.allowed:
        raise PermissionDenied(
            f"actor {actor_id} lacks {permission_key!r} on "
            f"{_project_scope_label(conn, project_id)}"
        )
    return decision


def org_permission_decision(
    conn: Any,
    *,
    actor_id: int,
    org_id: int,
    permission_key: str,
) -> PermissionDecision:
    """Authorize an ORG-scoped operation against a specific org (no project).

    Used for operations whose blast radius is an org itself — managing the org,
    granting org roles, creating projects, listing all projects. The org
    ``admin`` role is all-access by construction (drift-proof wildcard);
    otherwise an explicitly-granted org role must carry the permission.
    """
    p = _p(conn)
    admin_row = conn.execute(
        "SELECT 1 FROM actor_org_roles aor "
        "JOIN roles r ON r.id = aor.role_id "
        f"WHERE aor.org_id = {p} AND aor.actor_id = {p} AND r.name = {p} LIMIT 1",
        (org_id, actor_id, ROLE_ADMIN),
    ).fetchone()
    if admin_row is not None:
        return PermissionDecision(
            actor_id=actor_id,
            project_id=None,
            permission_key=permission_key,
            allowed=True,
            role_names=(ROLE_ADMIN,),
            org_id=org_id,
        )
    rows = conn.execute(
        "SELECT r.name "
        "FROM actor_org_roles aor "
        "JOIN roles r ON r.id = aor.role_id "
        "JOIN role_permissions rp ON rp.role_id = r.id "
        "JOIN permissions perm ON perm.id = rp.permission_id "
        f"WHERE aor.org_id = {p} AND aor.actor_id = {p} AND perm.key = {p} "
        "ORDER BY r.name",
        (org_id, actor_id, permission_key),
    ).fetchall()
    roles = tuple(sorted({str(row[0]) for row in rows}))
    return PermissionDecision(
        actor_id=actor_id,
        project_id=None,
        permission_key=permission_key,
        allowed=bool(roles),
        role_names=roles,
        org_id=org_id,
    )


def require_org_permission(
    conn: Any,
    *,
    actor_id: int,
    org_id: int,
    permission_key: str,
) -> PermissionDecision:
    """Return decision when allowed; raise :class:`PermissionDenied` otherwise."""
    decision = org_permission_decision(
        conn,
        actor_id=actor_id,
        org_id=org_id,
        permission_key=permission_key,
    )
    if not decision.allowed:
        raise PermissionDenied(
            f"actor {actor_id} lacks {permission_key!r} on "
            f"org {_org_scope_label(conn, org_id)}"
        )
    return decision


__all__ = [
    "org_permission_decision",
    "permission_decision",
    "require_org_permission",
    "require_permission",
]
