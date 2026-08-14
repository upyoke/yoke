"""GitHub Actions relay names a missing project on the queried plane."""

from __future__ import annotations

from pydantic import BaseModel

from runtime.api.fixtures import pg_testdb
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain.actor_permissions import (
    ROLE_OWNER,
    grant_actor_project_role,
    seed_roles_and_permissions,
)
from yoke_core.domain.auth_schema import create_auth_tables
from yoke_core.domain.function_unresolved_project import GENERIC_UNRESOLVED_PROJECT
from yoke_core.domain.org_schema import seed_default_org
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


def _conn():
    name = pg_testdb.create_test_database()
    conn = pg_testdb.drop_database_on_close(
        pg_testdb.connect_test_database(name), name,
    )
    create_core_tables(conn)
    seed_project_identities(conn)
    create_actor_identity_tables(conn)
    create_auth_tables(conn)
    seed_default_org(conn)
    seed_roles_and_permissions(conn)
    return conn


def test_github_actions_names_the_plane_when_the_project_is_missing(monkeypatch):
    monkeypatch.setenv("YOKE_ENVIRONMENT", "stage")
    conn = _conn()
    try:
        actor_id = int(
            conn.execute(
                "INSERT INTO actors (kind, created_at) "
                "VALUES ('human', '2026-01-01T00:00:00Z') RETURNING id"
            ).fetchone()[0]
        )
        grant_actor_project_role(
            conn,
            actor_id=actor_id,
            project_id=resolve_project_id(conn, "yoke"),
            role_name=ROLE_OWNER,
            granted_by_actor_id=actor_id,
        )
        conn.commit()
        entry = RegistryEntry(
            function_id="github_actions.wait_run",
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
        request = FunctionCallRequest(
            function="github_actions.wait_run",
            actor=ActorContext(actor_id=str(actor_id), session_id="s"),
            target=TargetRef(kind="global"),
            payload={
                "project": "platform",
                "repo": "upyoke/platform",
                "run_id": "1",
            },
        )
        permission = check_dispatch_permission(conn, entry, request)
        assert permission.error is not None
        assert permission.error.error is not None
        message = permission.error.error.message
        assert "platform" in message
        assert "stage" in message
        assert "not registered" in message
        assert GENERIC_UNRESOLVED_PROJECT not in message
    finally:
        conn.close()
