# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

from runtime.api.fixtures.actor_roles import seed_org_role, seed_project_role

import pytest

from pydantic import BaseModel

from yoke_core.domain.actor_permissions import (
    ROLE_ADMIN,
    ROLE_INFRASTRUCTURE_CI,
    ROLE_OWNER,
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

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)

from yoke_core.domain.yoke_function_permissions import check_dispatch_permission

from yoke_core.domain.yoke_function_registry import RegistryEntry


class EmptyModel(BaseModel):
    pass


@pytest.fixture
def conn():
    from runtime.api.fixtures import pg_testdb

    name = pg_testdb.create_test_database()
    c = pg_testdb.drop_database_on_close(pg_testdb.connect_test_database(name), name)
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


def _org_of(conn, project_id: int) -> int:
    row = conn.execute(
        "SELECT org_id FROM projects WHERE id = %s", (project_id,)
    ).fetchone()
    return int(row[0])


def _project_owner(conn, project_id: int) -> int:
    actor_id = _new_actor(conn)
    seed_project_role(
        conn,
        actor_id=actor_id,
        project_id=project_id,
        role_name=ROLE_OWNER,
        granted_by_actor_id=actor_id,
    )
    return actor_id


def _org_admin(conn, org_id: int) -> int:
    actor_id = _new_actor(conn)
    seed_org_role(
        conn,
        actor_id=actor_id,
        org_id=org_id,
        role_name=ROLE_ADMIN,
        granted_by_actor_id=actor_id,
    )
    return actor_id


def _entry(function_id: str, *, side_effects: bool = True) -> RegistryEntry:
    return RegistryEntry(
        function_id=function_id,
        handler=lambda _request: None,
        request_model=EmptyModel,
        response_model=EmptyModel,
        stability="stable",
        owner_module=__name__,
        target_kinds=("item",),
        side_effects=("db_write",) if side_effects else (),
        emitted_event_names=(),
        guardrails=(),
        adapter_status="live",
    )


def _request(
    actor_id, function_id: str, *, project: str | None = None
) -> FunctionCallRequest:
    target = (
        TargetRef(kind="item", project_id=project)
        if project is not None
        else TargetRef(kind="global")
    )
    return FunctionCallRequest(
        function=function_id,
        actor=ActorContext(actor_id=str(actor_id), session_id="s-1"),
        target=target,
        payload={},
    )


def _no_actor_request(function_id: str) -> FunctionCallRequest:
    return FunctionCallRequest(
        function=function_id,
        actor=ActorContext(actor_id="", session_id="s-1"),
        target=TargetRef(kind="global"),
        payload={},
    )


def _payload_request(actor_id, function_id: str, payload: dict) -> FunctionCallRequest:
    return FunctionCallRequest(
        function=function_id,
        actor=ActorContext(actor_id=str(actor_id), session_id="s-1"),
        target=TargetRef(kind="global"),
        payload=payload,
    )
