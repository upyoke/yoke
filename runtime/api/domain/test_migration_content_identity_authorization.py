"""Least-privilege authority for whole-control-plane migration verification."""

from __future__ import annotations

import sqlite3

from pydantic import BaseModel

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_contracts.migration_content_identity import FUNCTION_ID
from yoke_core.domain.actor_permissions import (
    PERM_DB_READ_RAW,
    PERM_EVENTS_READ,
    PERM_GITHUB_ACTIONS_RUN_READ,
    PERM_GITHUB_ACTIONS_VARIABLE_READ,
    PERM_GITHUB_ACTIONS_WORKFLOW_DISPATCH,
    PERM_GITHUB_RELEASE_CREATE,
    PERM_MIGRATION_CONTENT_IDENTITY_VERIFY,
    PERM_RELEASE_PIN_RECORD,
    ROLE_DEPLOYMENT_CI,
    ROLE_MIGRATION_VERIFICATION_CI,
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
        "INSERT INTO actors (kind, system_component, created_at) "
        "VALUES ('system', 'release-test', 'now')"
    )
    conn.commit()
    return int(cursor.lastrowid)


def _entry(function_id: str) -> RegistryEntry:
    return RegistryEntry(
        function_id=function_id,
        handler=lambda _request: None,
        request_model=EmptyModel,
        response_model=EmptyModel,
        stability="stable",
        owner_module=__name__,
        target_kinds=("global",),
        side_effects=(),
        emitted_event_names=(),
        guardrails=(),
        adapter_status="live",
    )


def _request(actor_id: int, function_id: str) -> FunctionCallRequest:
    return FunctionCallRequest(
        function=function_id,
        actor=ActorContext(actor_id=str(actor_id), session_id="release-ci"),
        target=TargetRef(kind="global"),
        payload={},
    )


def _role_permissions(conn: sqlite3.Connection, role_name: str) -> set[str]:
    rows = conn.execute(
        "SELECT p.key FROM roles r "
        "JOIN role_permissions rp ON rp.role_id = r.id "
        "JOIN permissions p ON p.id = rp.permission_id "
        "WHERE r.name = ?",
        (role_name,),
    ).fetchall()
    return {str(row[0]) for row in rows}


def test_release_roles_keep_project_and_control_plane_authority_separate() -> None:
    conn = _conn()
    try:
        deployment_permissions = {
            PERM_EVENTS_READ,
            PERM_GITHUB_ACTIONS_WORKFLOW_DISPATCH,
            PERM_GITHUB_ACTIONS_RUN_READ,
            PERM_GITHUB_ACTIONS_VARIABLE_READ,
            PERM_GITHUB_RELEASE_CREATE,
            PERM_RELEASE_PIN_RECORD,
        }
        assert _role_permissions(conn, ROLE_DEPLOYMENT_CI) == deployment_permissions
        assert _role_permissions(conn, ROLE_MIGRATION_VERIFICATION_CI) == {
            PERM_MIGRATION_CONTENT_IDENTITY_VERIFY
        }
        assert PERM_DB_READ_RAW not in _role_permissions(
            conn, ROLE_MIGRATION_VERIFICATION_CI
        )
    finally:
        conn.close()


def test_narrow_org_grant_allows_verification_while_raw_read_stays_denied() -> None:
    conn = _conn()
    try:
        actor_id = _actor(conn)
        project_id = resolve_project_id(conn, "yoke")
        grant_actor_project_role(
            conn,
            actor_id=actor_id,
            project_id=project_id,
            role_name=ROLE_DEPLOYMENT_CI,
            granted_by_actor_id=actor_id,
        )
        semantic_entry = _entry(FUNCTION_ID)
        db_read_entry = _entry("db.read.run")

        before = check_dispatch_permission(
            conn, semantic_entry, _request(actor_id, FUNCTION_ID)
        )
        assert before.error is not None
        assert before.permission_key == PERM_MIGRATION_CONTENT_IDENTITY_VERIFY

        org_id = org_id_by_slug(conn, "default")
        assert org_id is not None
        grant_actor_org_role(
            conn,
            actor_id=actor_id,
            org_id=org_id,
            role_name=ROLE_MIGRATION_VERIFICATION_CI,
            granted_by_actor_id=actor_id,
        )

        allowed = check_dispatch_permission(
            conn, semantic_entry, _request(actor_id, FUNCTION_ID)
        )
        raw_denied = check_dispatch_permission(
            conn, db_read_entry, _request(actor_id, "db.read.run")
        )
        assert allowed.error is None
        assert allowed.permission_key == PERM_MIGRATION_CONTENT_IDENTITY_VERIFY
        assert raw_denied.error is not None
        assert raw_denied.permission_key == PERM_DB_READ_RAW
    finally:
        conn.close()
