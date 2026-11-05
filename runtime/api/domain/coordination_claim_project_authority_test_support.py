# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

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

from yoke_core.domain.coordination_claim_keys import (
    CoordinationKeyError,
    key_for_target,
    target_for_key,
)

from yoke_core.domain.function_target_resolution import resolve_project_context

from yoke_core.domain.org_schema import seed_default_org

from yoke_core.domain.project_identity import resolve_project_id

from yoke_core.domain.project_seed_test_helpers import seed_project_identities

from yoke_core.domain.schema_init_actor_path_claim_tables import (
    create_actor_path_claim_tables,
)

from yoke_core.domain.schema_init_path_tables import create_path_registry_tables

from yoke_core.domain.schema_init_tables import create_core_tables

from yoke_core.domain.work_claim_targets import (
    TARGET_KIND_DEPLOY_SERIALIZATION,
    WorkClaimTarget,
    make_qa_admission_target,
)

from yoke_core.domain.yoke_function_permissions import check_dispatch_permission

from yoke_core.domain.yoke_function_registry import RegistryEntry


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


def _qa_host_claim(conn: Any, *, test_machine: str, session_id: str) -> int:
    """Insert a machine-scoped QA_HOST row built by the production constructor."""
    target = make_qa_admission_target(test_machine)
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
