"""A person's one role on one project, set or removed by an org admin.

A person with no org role reaches only the projects granted here, so this is
how someone gets one project and not another. Each change runs in one locked
transaction through the project-grant writers in
:mod:`yoke_core.domain.actor_role_grants`, which replace a person's role on a
project rather than add a second one.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from yoke_core.domain.actor_role import (
    ActorRoleRefused,
    _p,
    lock_person,
    require_human_org_role,
)
from yoke_core.domain.actor_role_grants import (
    grant_actor_project_role,
    revoke_actor_project_role,
)


@dataclass(frozen=True)
class ProjectRoleChange:
    actor_id: int
    project: str
    role: str | None
    previous_roles: list[str]
    changed: bool


def project_roles_of(conn: Any, actor_id: int, project_id: int) -> list[str]:
    """Every role the actor holds directly on ``project_id``, by name."""
    p = _p(conn)
    rows = conn.execute(
        "SELECT r.name FROM actor_project_roles apr JOIN roles r ON r.id = apr.role_id "
        f"WHERE apr.actor_id = {p} AND apr.project_id = {p} ORDER BY r.name",
        (actor_id, project_id),
    ).fetchall()
    return [str(row[0]) for row in rows]


def _org_project(conn: Any, project: str, org_id: int) -> tuple[int, str]:
    """Resolve a project of this org to its id and slug, or refuse by name."""
    from yoke_core.domain.project_identity import resolve_project

    try:
        ident = resolve_project(conn, project, required=True, org=org_id)
    except (LookupError, ValueError) as exc:
        raise ActorRoleRefused(
            "project_not_found",
            f"no project {project!r} in this organization ({exc}); "
            "run `yoke projects list` and pass one of its slugs",
        ) from exc
    assert ident is not None
    return ident.id, ident.slug


def set_actor_project_role(
    conn: Any, *, actor_id: int, project: str, role: str, caller_actor_id: int
) -> ProjectRoleChange:
    """Make ``role`` the person's only role on ``project``."""
    require_human_org_role(role)
    try:
        org_id = lock_person(conn, actor_id)
        project_id, slug = _org_project(conn, project, org_id)
        previous = project_roles_of(conn, actor_id, project_id)
        if previous != [role]:
            grant_actor_project_role(
                conn,
                actor_id=actor_id,
                project_id=project_id,
                role_name=role,
                granted_by_actor_id=caller_actor_id,
                commit=False,
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return ProjectRoleChange(actor_id, slug, role, previous, previous != [role])


def remove_actor_project_role(
    conn: Any, *, actor_id: int, project: str, caller_actor_id: int
) -> ProjectRoleChange:
    """Remove every role the person holds on ``project``; nothing held succeeds."""
    try:
        org_id = lock_person(conn, actor_id)
        project_id, slug = _org_project(conn, project, org_id)
        previous = project_roles_of(conn, actor_id, project_id)
        for held in previous:
            revoke_actor_project_role(
                conn,
                actor_id=actor_id,
                project_id=project_id,
                role_name=held,
                caller_actor_id=caller_actor_id,
                commit=False,
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return ProjectRoleChange(actor_id, slug, None, previous, bool(previous))
