"""Whole-universe authorization uses sole-organization admin authority."""

from yoke_core.domain.project_identity import resolve_project_id
from yoke_core.domain.yoke_function_permissions import check_dispatch_permission
from runtime.api.domain.test_function_authz_scope_routing import (
    _entry,
    _org_admin,
    _org_of,
    _project_owner,
    _request,
    conn,
)


_FIXTURES = (conn,)


def test_control_plane_op_requires_sole_org_admin_ignoring_project_slug(conn):
    yoke = resolve_project_id(conn, "yoke")
    externalwebapp = resolve_project_id(conn, "externalwebapp")
    externalwebapp_owner = _project_owner(conn, externalwebapp)
    yoke_owner = _project_owner(conn, yoke)
    org_admin = _org_admin(conn, _org_of(conn, yoke))
    entry = _entry("db.read.run", side_effects=False)

    denied = check_dispatch_permission(
        conn, entry, _request(externalwebapp_owner, "db.read.run", project="externalwebapp")
    )
    assert denied.error is not None
    assert denied.error.error.code == "permission_denied"

    denied_yoke_owner = check_dispatch_permission(
        conn, entry, _request(yoke_owner, "db.read.run", project="externalwebapp")
    )
    assert denied_yoke_owner.error is not None

    allowed = check_dispatch_permission(
        conn, entry, _request(org_admin, "db.read.run")
    )
    assert allowed.error is None
    assert allowed.project_id is None
    assert allowed.project_slug is None


def test_control_plane_op_denies_multi_org_universe(conn):
    yoke = resolve_project_id(conn, "yoke")
    org_admin = _org_admin(conn, _org_of(conn, yoke))
    conn.execute(
        "INSERT INTO organizations (id, slug, name, created_at) "
        "VALUES (99, 'other', 'Other', '2026-01-01T00:00:00Z')"
    )
    conn.commit()

    result = check_dispatch_permission(
        conn,
        _entry("db.read.run", side_effects=False),
        _request(org_admin, "db.read.run"),
    )

    assert result.error is not None
    assert "require exactly one organization" in result.error.error.message
