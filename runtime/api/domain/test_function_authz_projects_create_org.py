"""Project creation authorization for explicit organization targets."""

from __future__ import annotations

from runtime.api.domain.test_function_authz_scope_routing import (
    _entry,
    _org_admin,
    _org_of,
    _payload_request,
    conn,
)
from yoke_core.domain.project_identity import resolve_project_id


def _new_org(conn, slug: str) -> int:
    cur = conn.execute(
        "INSERT INTO organizations (slug, name, created_at) "
        "VALUES (%s, %s, '2026-01-01T00:00:00Z') RETURNING id",
        (slug, slug.title()),
    )
    org_id = int(cur.fetchone()[0])
    conn.commit()
    return org_id


def test_projects_create_uses_explicit_org_target(conn):
    yoke = resolve_project_id(conn, "yoke")
    default_org = _org_of(conn, yoke)
    default_org_admin = _org_admin(conn, default_org)
    installer_org = _new_org(conn, "installer-e2e")
    installer_admin = _org_admin(conn, installer_org)

    payload = {
        "slug": "installer-demo",
        "name": "Installer Demo",
        "org": "installer-e2e",
    }
    create = _entry("projects.create")

    assert check(conn, create, installer_admin, payload) is None
    assert check(conn, create, default_org_admin, payload) is not None


def check(conn, entry, actor_id: int, payload: dict):
    from yoke_core.domain.yoke_function_permissions import (
        check_dispatch_permission,
    )

    return check_dispatch_permission(
        conn, entry, _payload_request(actor_id, "projects.create", payload)
    ).error
