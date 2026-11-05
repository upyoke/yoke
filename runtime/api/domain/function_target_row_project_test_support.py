# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

from runtime.api.domain.coordination_claim_project_authority_test_support import conn as conn

import pytest

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

from yoke_core.domain.function_target_resolution import resolve_project_context

from yoke_core.domain.function_target_row_project import (
    resolve_ouroboros_entry_project,
    resolve_path_claim_project,
)

from yoke_core.domain.org_schema import seed_default_org

from yoke_core.domain.ouroboros_entries import cmd_insert_entry

from yoke_core.domain.project_identity import resolve_project_id

from yoke_core.domain.project_seed_test_helpers import seed_project_identities

from yoke_core.domain.schema_init_actor_path_claim_tables import (
    create_actor_path_claim_tables,
)

from yoke_core.domain.schema_init_path_tables import create_path_registry_tables

from yoke_core.domain.schema_init_tables import create_core_tables

from yoke_core.domain.workflow_registry import resolve_current_workflow_pin

from yoke_core.domain.yoke_function_permissions import check_dispatch_permission

from yoke_core.domain.yoke_function_registry import RegistryEntry

from pydantic import BaseModel

from runtime.api.fixtures import pg_testdb


def _project_owner(conn, project_id: int) -> int:
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


def _seed_item(conn, *, item_id: int, project_id: int) -> None:
    workflow_id, workflow_version_id = resolve_current_workflow_pin(conn, "issue")
    conn.execute(
        "INSERT INTO items (id, title, workflow_id, workflow_version_id, "
        "status, priority, created_at, updated_at, project_id, "
        "project_sequence) "
        "VALUES (%s, 'item', %s, %s, 'idea', 'medium', "
        "'2026-05-01T00:00:00Z', '2026-05-01T00:00:00Z', %s, %s)",
        (item_id, workflow_id, workflow_version_id, project_id, item_id),
    )
    conn.commit()


def _seed_path_claim(conn, *, claim_id: int, item_id: int) -> None:
    conn.execute(
        "INSERT INTO path_claims ("
        "id, state, mode, owner_kind, owner_item_id, integration_target, "
        "registered_at) "
        "VALUES (%s, 'planned', 'exclusive', 'item', %s, 'main', "
        "'2026-05-01T00:00:00Z')",
        (claim_id, item_id),
    )
    conn.commit()
