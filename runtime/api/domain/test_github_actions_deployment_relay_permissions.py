"""Least-privilege authorization for hosted deployment workflow relays."""

from __future__ import annotations

import sqlite3

from pydantic import BaseModel

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain.actor_permissions import (
    PERM_GITHUB_ACTIONS_RUN_READ,
    PERM_GITHUB_ACTIONS_VARIABLE_READ,
    PERM_GITHUB_ACTIONS_WORKFLOW_DISPATCH,
    PERM_GITHUB_RELEASE_CREATE,
    PERM_PROJECT_ADMIN,
    PERM_PROJECT_INSTALL,
    PERM_PROJECT_RENDER_READ,
    ROLE_ADMIN,
    ROLE_DEPLOYMENT_CI,
    ROLE_OWNER,
    grant_actor_org_role,
    grant_actor_project_role,
    seed_roles_and_permissions,
)
from yoke_core.domain.auth_schema import create_auth_tables
from yoke_core.domain.org_schema import org_id_by_slug, seed_default_org
from yoke_core.domain.project_identity import resolve_project_id
from yoke_core.domain.project_seed_test_helpers import seed_project_identities
from yoke_core.domain.schema_init_actor_path_claim_tables import (
    create_actor_identity_tables,
)
from yoke_core.domain.schema_init_tables import create_core_tables
from yoke_core.domain.yoke_function_permissions import check_dispatch_permission
from yoke_core.domain.yoke_function_registry import RegistryEntry


class EmptyModel(BaseModel):
    pass


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    create_core_tables(conn)
    seed_project_identities(conn)
    create_actor_identity_tables(conn)
    create_auth_tables(conn)
    seed_default_org(conn)
    seed_roles_and_permissions(conn)
    return conn


def _actor(conn: sqlite3.Connection) -> int:
    cursor = conn.execute(
        "INSERT INTO actors (kind, created_at) VALUES ('human', '2026-01-01T00:00:00Z')"
    )
    conn.commit()
    return int(cursor.lastrowid)


def _entry(function_id: str, *, write: bool) -> RegistryEntry:
    return RegistryEntry(
        function_id=function_id,
        handler=lambda _request: None,
        request_model=EmptyModel,
        response_model=EmptyModel,
        stability="stable",
        owner_module=__name__,
        target_kinds=("global",),
        side_effects=("github_write",) if write else (),
        emitted_event_names=(),
        guardrails=(),
        adapter_status="live",
    )


def _request(
    actor_id: int,
    function_id: str,
    project: str,
    *,
    target_project: str | None = None,
) -> FunctionCallRequest:
    return FunctionCallRequest(
        function=function_id,
        actor=ActorContext(actor_id=str(actor_id), session_id="ci-relay"),
        target=TargetRef(kind="global", project_id=target_project),
        payload={"project": project},
    )


def _role_permission_keys(conn: sqlite3.Connection, role: str) -> set[str]:
    rows = conn.execute(
        "SELECT p.key FROM roles r "
        "JOIN role_permissions rp ON rp.role_id = r.id "
        "JOIN permissions p ON p.id = rp.permission_id "
        "WHERE r.name = ? ORDER BY p.key",
        (role,),
    ).fetchall()
    return {str(row[0]) for row in rows}


def test_deployment_ci_role_carries_only_required_ci_permissions() -> None:
    conn = _conn()
    try:
        relay_permissions = {
            PERM_GITHUB_ACTIONS_WORKFLOW_DISPATCH,
            PERM_GITHUB_ACTIONS_RUN_READ,
            PERM_GITHUB_ACTIONS_VARIABLE_READ,
            PERM_GITHUB_RELEASE_CREATE,
        }
        assert _role_permission_keys(conn, ROLE_DEPLOYMENT_CI) == relay_permissions
        assert relay_permissions <= _role_permission_keys(conn, ROLE_OWNER)
        assert relay_permissions <= _role_permission_keys(conn, ROLE_ADMIN)
        assert PERM_PROJECT_ADMIN not in _role_permission_keys(conn, ROLE_DEPLOYMENT_CI)
        assert PERM_PROJECT_INSTALL not in _role_permission_keys(
            conn, ROLE_DEPLOYMENT_CI
        )
        assert PERM_PROJECT_RENDER_READ not in _role_permission_keys(
            conn, ROLE_DEPLOYMENT_CI
        )
    finally:
        conn.close()


def test_catalog_reseed_removes_stale_ci_install_and_render_permissions() -> None:
    conn = _conn()
    try:
        for permission_key in (PERM_PROJECT_INSTALL, PERM_PROJECT_RENDER_READ):
            conn.execute(
                "INSERT INTO role_permissions (role_id, permission_id, created_at) "
                "SELECT r.id, p.id, '2026-01-01T00:00:00Z' "
                "FROM roles r, permissions p "
                "WHERE r.name = ? AND p.key = ?",
                (ROLE_DEPLOYMENT_CI, permission_key),
            )
        conn.commit()
        assert PERM_PROJECT_INSTALL in _role_permission_keys(conn, ROLE_DEPLOYMENT_CI)
        assert PERM_PROJECT_RENDER_READ in _role_permission_keys(
            conn, ROLE_DEPLOYMENT_CI
        )

        seed_roles_and_permissions(conn)

        assert PERM_PROJECT_INSTALL not in _role_permission_keys(
            conn, ROLE_DEPLOYMENT_CI
        )
        assert PERM_PROJECT_RENDER_READ not in _role_permission_keys(
            conn, ROLE_DEPLOYMENT_CI
        )
    finally:
        conn.close()


def test_relay_can_dispatch_and_read_only_deploy_reporting_surfaces() -> None:
    conn = _conn()
    try:
        actor_id = _actor(conn)
        externalwebapp_id = resolve_project_id(conn, "externalwebapp")
        grant_actor_project_role(
            conn,
            actor_id=actor_id,
            project_id=externalwebapp_id,
            role_name=ROLE_DEPLOYMENT_CI,
            granted_by_actor_id=actor_id,
        )
        allowed = {
            "github_actions.workflow.dispatch": True,
            "github_actions.workflow.dispatch_once": True,
            "github_actions.workflow.find_run": False,
            "github_actions.run.jobs_count": False,
            "github_actions.wait_run": False,
            "github_actions.check_ci": False,
            "github_actions.variable.get": False,
            "github.release.create_next_tag": True,
        }
        for function_id, write in allowed.items():
            decision = check_dispatch_permission(
                conn,
                _entry(function_id, write=write),
                _request(actor_id, function_id, "externalwebapp"),
            )
            assert decision.error is None, function_id

        for function_id, write in {
            "github_actions.variable.set": True,
            "github_actions.secret.set": True,
            "github_actions.runners.status": False,
            "github_actions.webhook.configure": True,
        }.items():
            decision = check_dispatch_permission(
                conn,
                _entry(function_id, write=write),
                _request(actor_id, function_id, "externalwebapp"),
            )
            assert decision.error is not None, function_id
            assert decision.permission_key == PERM_PROJECT_ADMIN

        cross_project = check_dispatch_permission(
            conn,
            _entry("github_actions.workflow.dispatch", write=True),
            _request(actor_id, "github_actions.workflow.dispatch", "yoke"),
        )
        assert cross_project.error is not None
    finally:
        conn.close()


def test_relay_rejects_conflicting_target_and_payload_when_both_are_authorized() -> None:
    conn = _conn()
    try:
        actor_id = _actor(conn)
        for project in ("yoke", "externalwebapp"):
            grant_actor_project_role(
                conn,
                actor_id=actor_id,
                project_id=resolve_project_id(conn, project),
                role_name=ROLE_DEPLOYMENT_CI,
                granted_by_actor_id=actor_id,
            )

        decision = check_dispatch_permission(
            conn,
            _entry("github_actions.workflow.dispatch", write=True),
            _request(
                actor_id,
                "github_actions.workflow.dispatch",
                "externalwebapp",
                target_project="yoke",
            ),
        )

        assert decision.error is not None
        assert decision.error.error is not None
        assert decision.error.error.code == "permission_denied"
    finally:
        conn.close()


def test_owner_and_org_admin_retain_all_github_actions_access() -> None:
    conn = _conn()
    try:
        externalwebapp_id = resolve_project_id(conn, "externalwebapp")
        owner_id = _actor(conn)
        admin_id = _actor(conn)
        grant_actor_project_role(
            conn,
            actor_id=owner_id,
            project_id=externalwebapp_id,
            role_name=ROLE_OWNER,
            granted_by_actor_id=owner_id,
        )
        org_id = org_id_by_slug(conn, "default")
        assert org_id is not None
        grant_actor_org_role(
            conn,
            actor_id=admin_id,
            org_id=org_id,
            role_name=ROLE_ADMIN,
            granted_by_actor_id=admin_id,
        )
        for actor_id in (owner_id, admin_id):
            for function_id in (
                "github_actions.workflow.dispatch",
                "github_actions.variable.set",
                "github_actions.runners.status",
                "github_actions.webhook.configure",
            ):
                decision = check_dispatch_permission(
                    conn,
                    _entry(function_id, write=True),
                    _request(actor_id, function_id, "externalwebapp"),
                )
                assert decision.error is None, (actor_id, function_id)
    finally:
        conn.close()
