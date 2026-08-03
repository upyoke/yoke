"""Shared fixtures for the items roster and items search handler tests.

Both reads answer within the same project-visibility boundary, so their
suites need the same actor grants, duplicate-slug projects, and
known-prefix projects to assert that boundary against.
"""

from __future__ import annotations

from runtime.api.conftest import insert_item
from yoke_core.domain.actor_permissions import (
    ROLE_VIEWER,
    grant_actor_project_role,
    seed_roles_and_permissions,
)
from yoke_core.domain.actors import seed_human_actor
from yoke_core.domain.org_schema import org_id_by_slug
from yoke_core.domain.project_identity import resolve_project_id
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)


def request_for(function_id: str, payload=None, actor_id="op") -> FunctionCallRequest:
    return FunctionCallRequest(
        function=function_id,
        actor=ActorContext(actor_id=str(actor_id), session_id="s-1"),
        target=TargetRef(kind="global"),
        payload=payload or {},
    )


def grant_project_viewer(conn, project: str) -> int:
    return grant_project_viewer_id(conn, resolve_project_id(conn, project))


def grant_project_viewer_id(conn, project_id: int) -> int:
    seed_roles_and_permissions(conn)
    actor_id = seed_human_actor(conn)
    grant_actor_project_role(
        conn,
        actor_id=actor_id,
        project_id=project_id,
        role_name=ROLE_VIEWER,
        granted_by_actor_id=actor_id,
    )
    return actor_id


def insert_prefixed_project(conn, *, project_id: int, prefix: str) -> int:
    default_org = org_id_by_slug(conn, "default")
    assert default_org is not None
    slug = prefix.lower()
    conn.execute(
        "INSERT INTO projects "
        "(id, org_id, slug, name, public_item_prefix, created_at) "
        "VALUES (%s, %s, %s, %s, %s, '2026-01-01T00:00:00Z')",
        (project_id, default_org, slug, slug, prefix),
    )
    return project_id


def insert_shared_slug_items(conn) -> tuple[int, int]:
    default_org = org_id_by_slug(conn, "default")
    assert default_org is not None
    other_org = conn.execute(
        "INSERT INTO organizations (slug, name, created_at) "
        "VALUES ('other', 'Other Org', '2026-01-01T00:00:00Z') "
        "RETURNING id"
    ).fetchone()[0]
    conn.execute(
        "INSERT INTO projects "
        "(id, org_id, slug, name, public_item_prefix, created_at) "
        "VALUES "
        "(110, %s, 'shared', 'Default Shared', 'DSH', '2026-01-01T00:00:00Z'), "
        "(111, %s, 'shared', 'Other Shared', 'OSH', '2026-01-01T00:00:00Z')",
        (default_org, other_org),
    )
    insert_item(conn, id=910, title="shared zorp default", project_id=110)
    insert_item(conn, id=911, title="shared zorp other", project_id=111)
    return 110, 111
