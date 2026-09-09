"""Source-development bootstrap orchestration for actor-bound API tokens."""

from __future__ import annotations

from typing import Any

from yoke_core.domain import db_backend
from yoke_core.domain.actor_permissions import (
    PROJECT_ROLES,
    ROLE_ADMIN,
    ROLE_OWNER,
    grant_actor_org_role,
    grant_actor_project_role,
    seed_roles_and_permissions,
)
from yoke_core.domain.actors import (
    seed_human_actor,
    seed_system_actor,
    set_actor_name,
    sole_human_actor_id,
)
from yoke_core.domain.api_tokens import CreatedToken, mint_token
from yoke_core.domain.org_schema import seed_default_org
from yoke_core.domain.project_identity import resolve_project_id


def _required_name(value: str, *, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return value.strip()


def _service_actor_authority(
    conn: Any,
    actor_id: int,
) -> tuple[set[tuple[int, str]], set[tuple[int, str]]]:
    """Return project and org grants carried by one service actor."""
    placeholder = "%s" if db_backend.connection_is_postgres(conn) else "?"
    project_rows = conn.execute(
        "SELECT apr.project_id, r.name FROM actor_project_roles apr "
        "JOIN roles r ON r.id = apr.role_id "
        f"WHERE apr.actor_id = {placeholder}",
        (actor_id,),
    ).fetchall()
    org_rows = conn.execute(
        "SELECT aor.org_id, r.name FROM actor_org_roles aor "
        "JOIN roles r ON r.id = aor.role_id "
        f"WHERE aor.actor_id = {placeholder}",
        (actor_id,),
    ).fetchall()
    return (
        {(int(row[0]), str(row[1])) for row in project_rows},
        {(int(row[0]), str(row[1])) for row in org_rows},
    )


def _assert_service_actor_scope(
    conn: Any,
    *,
    actor_id: int,
    project_id: int,
    role_name: str,
    allow_ungranted: bool,
) -> None:
    """Refuse minting when a named service actor carries broader authority."""
    project_grants, org_grants = _service_actor_authority(conn, actor_id)
    expected = {(project_id, role_name)}
    if org_grants or (project_grants and project_grants != expected):
        raise ValueError(
            "system_component already belongs to a service actor with "
            "different or broader authority; choose a distinct component name"
        )
    if not allow_ungranted and project_grants != expected:
        raise ValueError(
            "service actor project-role grant did not converge to the exact "
            "requested scope"
        )


def _human_actors_present(conn: Any) -> bool:
    return (
        conn.execute(
            "SELECT 1 FROM actors WHERE kind = 'human' LIMIT 1"
        ).fetchone()
        is not None
    )


def bootstrap_admin_token(
    conn: Any,
    *,
    actor_name: str,
    project: str | None,
    token_name: str,
) -> CreatedToken:
    """Create or resolve the admin actor, grant authority, and mint one token.

    ``actor_name`` names a human this call creates; it never selects one.
    A universe that already carries its single administrator keeps that
    actor whatever it is called, because the token being minted has to
    bind the identity that already holds this universe's authority — and
    a name is not that identity. A universe carrying several humans is
    past bootstrap, so the call refuses rather than guessing which of
    them the token should speak for.
    """
    seed_roles_and_permissions(conn)
    actor_id = sole_human_actor_id(conn)
    if actor_id is None:
        if _human_actors_present(conn):
            raise ValueError(
                "this universe carries more than one human actor, so which "
                "one an admin token should bind is not a bootstrap question; "
                "mint the token for an explicit actor instead"
            )
        actor_id = seed_human_actor(conn, actor_name)
    else:
        set_actor_name(conn, actor_id, actor_name)
    if project is None:
        org_id = seed_default_org(conn)
        grant_actor_org_role(
            conn,
            actor_id=actor_id,
            org_id=org_id,
            role_name=ROLE_ADMIN,
            granted_by_actor_id=actor_id,
        )
    else:
        project_id = resolve_project_id(conn, project)
        grant_actor_project_role(
            conn,
            actor_id=actor_id,
            project_id=project_id,
            role_name=ROLE_OWNER,
            granted_by_actor_id=actor_id,
        )
    return mint_token(conn, actor_id=actor_id, name=token_name)


def bootstrap_project_service_token(
    conn: Any,
    *,
    system_component: str,
    project: str | int,
    role_name: str,
    token_name: str,
) -> CreatedToken:
    """Resolve project authority, ensure one service actor/grant, and mint.

    Actor creation and the project-role grant are idempotent. Every invocation
    deliberately mints another active named token; callers install the new
    secret before revoking the superseded token id.
    """
    component = _required_name(system_component, field="system_component")
    role = _required_name(role_name, field="role_name")
    name = _required_name(token_name, field="token_name")
    if role not in PROJECT_ROLES:
        accepted = ", ".join(PROJECT_ROLES)
        raise ValueError(
            f"role_name {role!r} is not a project-scoped role; choose one of {accepted}"
        )

    # Resolve before creating durable actor state so an unknown or ambiguous
    # project fails without leaving an orphan service identity.
    project_id = resolve_project_id(conn, project)
    seed_roles_and_permissions(conn)
    actor_id = seed_system_actor(conn, component)
    _assert_service_actor_scope(
        conn,
        actor_id=actor_id,
        project_id=project_id,
        role_name=role,
        allow_ungranted=True,
    )
    grant_actor_project_role(
        conn,
        actor_id=actor_id,
        project_id=project_id,
        role_name=role,
    )
    _assert_service_actor_scope(
        conn,
        actor_id=actor_id,
        project_id=project_id,
        role_name=role,
        allow_ungranted=False,
    )
    return mint_token(conn, actor_id=actor_id, name=name)


__all__ = ["bootstrap_admin_token", "bootstrap_project_service_token"]
