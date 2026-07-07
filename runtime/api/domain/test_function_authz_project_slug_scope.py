"""Authorization routing for org-scoped project slugs."""

from __future__ import annotations

import sqlite3

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


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    create_core_tables(conn)
    seed_project_identities(conn)
    create_path_registry_tables(conn)
    create_actor_path_claim_tables(conn)
    create_auth_tables(conn)
    seed_default_org(conn)
    seed_roles_and_permissions(conn)
    return conn


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


def _request(actor_id: int, function_id: str, payload: dict) -> FunctionCallRequest:
    return FunctionCallRequest(
        function=function_id,
        actor=ActorContext(actor_id=str(actor_id), session_id="s-1"),
        target=TargetRef(kind="global"),
        payload=payload,
    )


def _actor(conn: sqlite3.Connection) -> int:
    cursor = conn.execute(
        "INSERT INTO actors (kind, created_at) "
        "VALUES ('human', '2026-01-01T00:00:00Z')"
    )
    conn.commit()
    return int(cursor.lastrowid)


def _grant_owner(conn: sqlite3.Connection, actor_id: int, project_id: int) -> None:
    grant_actor_project_role(
        conn,
        actor_id=actor_id,
        project_id=project_id,
        role_name=ROLE_OWNER,
        granted_by_actor_id=actor_id,
    )


def _insert_shared_projects(conn: sqlite3.Connection) -> tuple[int, int]:
    other_org = conn.execute(
        "INSERT INTO organizations (slug, name, created_at) "
        "VALUES ('other', 'Other Org', '2026-01-01T00:00:00Z')"
    ).lastrowid
    conn.execute(
        "INSERT INTO projects "
        "(id, org_id, slug, name, public_item_prefix, created_at) "
        "VALUES "
        "(210, 1, 'shared', 'Default Shared', 'DSH', '2026-01-01T00:00:00Z'), "
        "(211, ?, 'shared', 'Other Shared', 'OSH', '2026-01-01T00:00:00Z')",
        (other_org,),
    )
    conn.commit()
    return 210, 211


def test_project_payload_slug_resolves_inside_actor_visible_projects() -> None:
    conn = _conn()
    try:
        _, visible_project = _insert_shared_projects(conn)
        actor_id = _actor(conn)
        _grant_owner(conn, actor_id, visible_project)

        allowed = check_dispatch_permission(
            conn,
            _entry("projects.update"),
            _request(actor_id, "projects.update", {"slug": "shared", "name": "Shared"}),
        )

        assert allowed.error is None
        assert allowed.project_id == visible_project
        assert allowed.project_slug == "shared"
    finally:
        conn.close()


def test_board_scope_rejects_slug_ambiguous_inside_actor_visible_projects() -> None:
    conn = _conn()
    try:
        first, second = _insert_shared_projects(conn)
        actor_id = _actor(conn)
        _grant_owner(conn, actor_id, first)
        _grant_owner(conn, actor_id, second)

        denied = check_dispatch_permission(
            conn,
            _entry("board.data.get", side_effects=False),
            _request(actor_id, "board.data.get", {"scope": "shared"}),
        )

        assert denied.error is not None
        assert denied.error.error is not None
        assert denied.error.error.code == "ambiguous_project"
    finally:
        conn.close()
