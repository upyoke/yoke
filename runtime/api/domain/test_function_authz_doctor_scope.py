"""Permission routing for the Doctor function-call surface."""

from __future__ import annotations

import pytest
from pydantic import BaseModel

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
from yoke_core.domain.org_schema import seed_default_org
from yoke_core.domain.project_identity import resolve_project_id
from yoke_core.domain.project_seed_test_helpers import seed_project_identities
from yoke_core.domain.schema_init_actor_path_claim_tables import (
    create_actor_path_claim_tables,
)
from yoke_core.domain.schema_init_path_tables import create_path_registry_tables
from yoke_core.domain.schema_init_tables import create_core_tables
from yoke_core.domain.yoke_function_permissions import check_dispatch_permission
from yoke_core.domain.yoke_function_registry import RegistryEntry


class EmptyModel(BaseModel):
    pass


@pytest.fixture
def conn():
    from runtime.api.fixtures import pg_testdb

    name = pg_testdb.create_test_database()
    c = pg_testdb.drop_database_on_close(
        pg_testdb.connect_test_database(name), name
    )
    create_core_tables(c)
    seed_project_identities(c)
    create_path_registry_tables(c)
    create_actor_path_claim_tables(c)
    create_auth_tables(c)
    seed_default_org(c)
    seed_roles_and_permissions(c)
    yield c
    c.close()


def _new_actor(conn) -> int:
    cur = conn.execute(
        "INSERT INTO actors (kind, created_at) "
        "VALUES ('human', '2026-01-01T00:00:00Z') RETURNING id"
    )
    actor_id = int(cur.fetchone()[0])
    conn.commit()
    return actor_id


def _project_owner(conn, project_id: int) -> int:
    actor_id = _new_actor(conn)
    grant_actor_project_role(
        conn, actor_id=actor_id, project_id=project_id,
        role_name=ROLE_OWNER, granted_by_actor_id=actor_id,
    )
    return actor_id


def _entry() -> RegistryEntry:
    return RegistryEntry(
        function_id="doctor.run.run",
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


def _request(actor_id: int, payload: dict) -> FunctionCallRequest:
    return FunctionCallRequest(
        function="doctor.run.run",
        actor=ActorContext(actor_id=str(actor_id), session_id="s-1"),
        target=TargetRef(kind="global"),
        payload=payload,
    )


def test_project_safe_doctor_quick_routes_to_named_project(conn):
    externalwebapp = resolve_project_id(conn, "externalwebapp")
    externalwebapp_owner = _project_owner(conn, externalwebapp)

    result = check_dispatch_permission(
        conn,
        _entry(),
        _request(
            externalwebapp_owner,
            {
                "project": "externalwebapp",
                "quick": True,
                "full": False,
                "fix": False,
                "max_checks": 1,
                "skip_source_tree_checks": True,
            },
        ),
    )

    assert result.error is None
    assert result.project_slug == "externalwebapp"


def test_full_doctor_still_requires_control_plane_permission(conn):
    externalwebapp = resolve_project_id(conn, "externalwebapp")
    externalwebapp_owner = _project_owner(conn, externalwebapp)

    denied = check_dispatch_permission(
        conn,
        _entry(),
        _request(
            externalwebapp_owner,
            {"project": "externalwebapp", "quick": False, "full": True, "fix": False},
        ),
    )

    assert denied.error is not None
    assert denied.error.error.code == "permission_denied"


def test_doctor_quick_without_source_tree_skip_uses_control_plane_permission(conn):
    externalwebapp = resolve_project_id(conn, "externalwebapp")
    externalwebapp_owner = _project_owner(conn, externalwebapp)

    denied = check_dispatch_permission(
        conn,
        _entry(),
        _request(
            externalwebapp_owner,
            {"project": "externalwebapp", "quick": True, "full": False, "fix": False},
        ),
    )

    assert denied.error is not None
    assert denied.error.error.code == "permission_denied"
