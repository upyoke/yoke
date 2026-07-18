"""Project authorization boundary for flow declarations."""

from __future__ import annotations

from yoke_core.domain.project_identity import resolve_project_id
from yoke_core.domain.yoke_function_permissions import check_dispatch_permission
from runtime.api.domain.test_function_authz_scope_routing import (
    _entry,
    _project_owner,
    _request,
    conn,
)


def test_project_flow_declaration_is_project_admin_scoped(conn) -> None:
    project_id = resolve_project_id(conn, "yoke")
    other_project_id = resolve_project_id(conn, "externalwebapp")
    owner = _project_owner(conn, project_id)
    entry = _entry("deployment_flows.reconcile_project")

    allowed = check_dispatch_permission(
        conn,
        entry,
        _request(
            owner,
            "deployment_flows.reconcile_project",
            project="yoke",
        ),
    )
    assert allowed.error is None
    assert allowed.project_id == project_id

    denied = check_dispatch_permission(
        conn,
        entry,
        _request(
            owner,
            "deployment_flows.reconcile_project",
            project="externalwebapp",
        ),
    )
    assert denied.error is not None
    assert denied.error.error.code == "permission_denied"
    assert denied.project_id == other_project_id
