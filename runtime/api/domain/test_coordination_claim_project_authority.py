"""A coordination claim names its own project when the caller cannot.

Releasing a hold by the row id its acquire handed back, and listing the holds
of one session, both address real tenant rows without naming a project. The
permission check still runs against the project those rows record — this only
supplies the target the check needs, so ownership and tenancy are unchanged.
"""

from __future__ import annotations

from typing import Any

import pytest
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
from yoke_core.domain.coordination_claim_keys import target_for_key
from yoke_core.domain.function_target_resolution import resolve_project_context
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
    name = pg_testdb.create_test_database()
    connection = pg_testdb.drop_database_on_close(
        pg_testdb.connect_test_database(name),
        name,
    )
    create_core_tables(connection)
    from yoke_core.domain.workflow_registry import converge_builtin_workflows
    from yoke_core.domain.workflow_schema import ensure_workflow_schema

    ensure_workflow_schema(connection)
    converge_builtin_workflows(connection)
    connection.commit()
    seed_project_identities(connection)
    create_path_registry_tables(connection)
    create_actor_path_claim_tables(connection)
    create_auth_tables(connection)
    seed_default_org(connection)
    seed_roles_and_permissions(connection)
    yield connection
    connection.close()


def _entry(function_id: str) -> RegistryEntry:
    return RegistryEntry(
        function_id=function_id,
        handler=lambda _request: None,
        request_model=EmptyModel,
        response_model=EmptyModel,
        stability="stable",
        owner_module=__name__,
        target_kinds=("global",),
        side_effects=("db_write",),
        emitted_event_names=(),
        guardrails=(),
        adapter_status="live",
    )


def _project_owner(conn: Any, project_id: int) -> int:
    cur = conn.execute(
        "INSERT INTO actors (kind, created_at) "
        "VALUES ('human', '2026-01-01T00:00:00Z') RETURNING id"
    )
    actor_id = int(cur.fetchone()[0])
    grant_actor_project_role(
        conn,
        actor_id=actor_id,
        project_id=project_id,
        role_name=ROLE_OWNER,
        granted_by_actor_id=actor_id,
    )
    return actor_id


def _session(conn: Any, session_id: str, project_id: int) -> None:
    conn.execute(
        "INSERT INTO harness_sessions "
        "(session_id, executor, provider, model, workspace, project_id, "
        "offered_at, last_heartbeat) "
        "VALUES (%s, 'codex', 'openai', 'gpt', '/tmp', %s, %s, %s)",
        (
            session_id,
            project_id,
            "2026-09-15T00:00:00Z",
            "2026-09-15T00:00:00Z",
        ),
    )
    conn.commit()


def _deploy_claim(conn: Any, *, project: str, session_id: str) -> int:
    """Insert the row an acquire writes, built by the production constructor.

    The scope is what the resolver reads, so it is built through
    ``target_for_key`` rather than hand-shaped here.
    """
    identity = resolve_project_id(conn, project)
    target = target_for_key(
        f"DEPLOY:{project}", project_id=identity, project_slug=project
    )
    cur = conn.execute(
        "INSERT INTO work_claims "
        "(session_id, target_kind, scope, claimed_at, last_heartbeat) "
        "VALUES (%s, %s, %s, %s, %s) RETURNING id",
        (
            session_id,
            target.kind,
            target.scope_json(),
            "2026-09-15T00:00:00Z",
            "2026-09-15T00:00:00Z",
        ),
    )
    claim_id = int(cur.fetchone()[0])
    conn.commit()
    return claim_id


def _release_request(actor_id: int, payload: dict) -> FunctionCallRequest:
    return FunctionCallRequest(
        function="claims.coordination_claim.release",
        actor=ActorContext(actor_id=str(actor_id), session_id="holder-session"),
        target=TargetRef(kind="global"),
        payload=payload,
    )


def test_release_by_claim_id_alone_resolves_the_claim_project(conn: Any):
    yoke = resolve_project_id(conn, "yoke")
    actor_id = _project_owner(conn, yoke)
    _session(conn, "holder-session", yoke)
    claim_id = _deploy_claim(conn, project="yoke", session_id="holder-session")
    entry = _entry("claims.coordination_claim.release")

    request = _release_request(actor_id, {"claim_id": claim_id, "reason": "done"})

    assert resolve_project_context(conn, entry, request) == (yoke, "yoke")
    allowed = check_dispatch_permission(conn, entry, request)
    assert allowed.error is None
    assert allowed.project_id == yoke


def test_explicit_project_and_key_still_resolve(conn: Any):
    yoke = resolve_project_id(conn, "yoke")
    actor_id = _project_owner(conn, yoke)
    _session(conn, "holder-session", yoke)
    entry = _entry("claims.coordination_claim.release")

    request = _release_request(
        actor_id, {"project_id": "yoke", "key": "DEPLOY:yoke", "reason": "done"}
    )

    assert resolve_project_context(conn, entry, request) == (yoke, "yoke")
    assert check_dispatch_permission(conn, entry, request).error is None


def test_an_actor_without_the_claim_project_is_still_refused(conn: Any):
    """Resolving the target must not hand authority to a different tenant."""
    yoke = resolve_project_id(conn, "yoke")
    external = resolve_project_id(conn, "externalwebapp")
    _project_owner(conn, yoke)
    outsider = _project_owner(conn, external)
    _session(conn, "holder-session", yoke)
    claim_id = _deploy_claim(conn, project="yoke", session_id="holder-session")
    entry = _entry("claims.coordination_claim.release")

    request = _release_request(outsider, {"claim_id": claim_id, "reason": "done"})

    assert resolve_project_context(conn, entry, request) == (yoke, "yoke")
    assert check_dispatch_permission(conn, entry, request).error is not None


def test_a_claim_id_naming_no_row_resolves_nothing(conn: Any):
    yoke = resolve_project_id(conn, "yoke")
    actor_id = _project_owner(conn, yoke)
    entry = _entry("claims.coordination_claim.release")

    request = _release_request(actor_id, {"claim_id": 987654, "reason": "done"})

    assert resolve_project_context(conn, entry, request) is None
    assert check_dispatch_permission(conn, entry, request).error is not None


def test_listing_by_session_alone_resolves_that_session_project(conn: Any):
    yoke = resolve_project_id(conn, "yoke")
    actor_id = _project_owner(conn, yoke)
    _session(conn, "holder-session", yoke)
    entry = _entry("claims.coordination_claim.list")

    request = FunctionCallRequest(
        function="claims.coordination_claim.list",
        actor=ActorContext(actor_id=str(actor_id), session_id="holder-session"),
        target=TargetRef(kind="global"),
        payload={"session_id": "holder-session"},
    )

    assert resolve_project_context(conn, entry, request) == (yoke, "yoke")
