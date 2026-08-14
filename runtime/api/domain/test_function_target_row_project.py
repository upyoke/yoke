"""Target-row project resolution for path claims and ouroboros entries."""

from __future__ import annotations

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


def _entry(function_id: str, *, side_effects: bool = False) -> RegistryEntry:
    return RegistryEntry(
        function_id=function_id,
        handler=lambda _request: None,
        request_model=EmptyModel,
        response_model=EmptyModel,
        stability="stable",
        owner_module=__name__,
        target_kinds=("path_claim", "global"),
        side_effects=("db_write",) if side_effects else (),
        emitted_event_names=(),
        guardrails=(),
        adapter_status="live",
    )


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
    workflow_id, workflow_version_id = resolve_current_workflow_pin(
        conn, "issue"
    )
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


def test_resolve_path_claim_project_from_owning_item(conn):
    yoke = resolve_project_id(conn, "yoke")
    _seed_item(conn, item_id=42, project_id=yoke)
    _seed_path_claim(conn, claim_id=1048, item_id=42)
    assert resolve_path_claim_project(conn, 1048) == (yoke, "yoke")


def test_resolve_ouroboros_entry_project_from_note_row(conn):
    yoke = resolve_project_id(conn, "yoke")
    entry_id = int(
        cmd_insert_entry(
            conn,
            timestamp="2026-08-10T18:03:05Z",
            agent="test",
            context=None,
            category="field-note-observation",
            body="note body",
            project="yoke",
        )
    )
    assert resolve_ouroboros_entry_project(conn, entry_id) == (yoke, "yoke")


def test_claims_path_override_resolves_project_from_payload_claim_id(conn):
    yoke = resolve_project_id(conn, "yoke")
    _seed_item(conn, item_id=42, project_id=yoke)
    _seed_path_claim(conn, claim_id=1048, item_id=42)
    entry = _entry("claims.path.override", side_effects=True)
    request = FunctionCallRequest(
        function="claims.path.override",
        actor=ActorContext(actor_id="1", session_id="s-1"),
        target=TargetRef(kind="global"),
        payload={"path_claim_id": 1048},
    )
    assert resolve_project_context(conn, entry, request) == (yoke, "yoke")


def test_claims_path_get_authorizes_from_path_claim_row(conn):
    yoke = resolve_project_id(conn, "yoke")
    actor_id = _project_owner(conn, yoke)
    _seed_item(conn, item_id=42, project_id=yoke)
    _seed_path_claim(conn, claim_id=1048, item_id=42)
    entry = _entry("claims.path.get")
    request = FunctionCallRequest(
        function="claims.path.get",
        actor=ActorContext(actor_id=str(actor_id), session_id="s-1"),
        target=TargetRef(kind="path_claim", path_claim_id=1048),
        payload={},
    )
    allowed = check_dispatch_permission(conn, entry, request)
    assert allowed.error is None
    assert allowed.project_id == yoke
    assert resolve_project_context(conn, entry, request) == (yoke, "yoke")


def test_field_note_promote_authorizes_from_note_project_without_flag(conn):
    yoke = resolve_project_id(conn, "yoke")
    actor_id = _project_owner(conn, yoke)
    entry_id = int(
        cmd_insert_entry(
            conn,
            timestamp="2026-08-10T18:03:05Z",
            agent="test",
            context=None,
            category="field-note-observation",
            body="promote me",
            project="yoke",
        )
    )
    entry = _entry("ouroboros.field_note.promote", side_effects=True)
    request = FunctionCallRequest(
        function="ouroboros.field_note.promote",
        actor=ActorContext(actor_id=str(actor_id), session_id="s-1"),
        target=TargetRef(kind="global"),
        payload={"entry_id": entry_id, "title": "Promote without --project"},
    )
    allowed = check_dispatch_permission(conn, entry, request)
    assert allowed.error is None
    assert allowed.project_id == yoke


def test_explicit_project_still_overrides_note_row(conn):
    external = resolve_project_id(conn, "externalwebapp")
    actor_id = _project_owner(conn, external)
    entry_id = int(
        cmd_insert_entry(
            conn,
            timestamp="2026-08-10T18:04:05Z",
            agent="test",
            context=None,
            category="field-note-observation",
            body="note on yoke",
            project="yoke",
        )
    )
    entry = _entry("ouroboros.field_note.promote", side_effects=True)
    request = FunctionCallRequest(
        function="ouroboros.field_note.promote",
        actor=ActorContext(actor_id=str(actor_id), session_id="s-1"),
        target=TargetRef(kind="global"),
        payload={
            "entry_id": entry_id,
            "title": "Override project",
            "project": "externalwebapp",
        },
    )
    allowed = check_dispatch_permission(conn, entry, request)
    assert allowed.error is None
    assert allowed.project_id == external


def test_mark_archived_authorizes_from_entry_row_without_flag(conn):
    yoke = resolve_project_id(conn, "yoke")
    actor_id = _project_owner(conn, yoke)
    entry_id = int(
        cmd_insert_entry(
            conn,
            timestamp="2026-08-12T13:00:00Z",
            agent="test",
            context=None,
            category="friction",
            body="archive me by row project",
            project="yoke",
        )
    )
    entry = _entry("ouroboros.entry.mark_archived", side_effects=True)
    request = FunctionCallRequest(
        function="ouroboros.entry.mark_archived",
        actor=ActorContext(actor_id=str(actor_id), session_id="s-1"),
        target=TargetRef(kind="global"),
        payload={"entry_id": entry_id},
    )
    allowed = check_dispatch_permission(conn, entry, request)
    assert allowed.error is None
    assert allowed.project_id == yoke


def test_mark_archived_all_reviewed_authorizes_from_explicit_project(conn):
    yoke = resolve_project_id(conn, "yoke")
    actor_id = _project_owner(conn, yoke)
    entry = _entry("ouroboros.entry.mark_archived", side_effects=True)
    request = FunctionCallRequest(
        function="ouroboros.entry.mark_archived",
        actor=ActorContext(actor_id=str(actor_id), session_id="s-1"),
        target=TargetRef(kind="global"),
        payload={"all_reviewed": True, "project": "yoke"},
    )
    allowed = check_dispatch_permission(conn, entry, request)
    assert allowed.error is None
    assert allowed.project_id == yoke


def test_mark_archived_all_reviewed_without_project_is_denied(conn):
    yoke = resolve_project_id(conn, "yoke")
    actor_id = _project_owner(conn, yoke)
    entry = _entry("ouroboros.entry.mark_archived", side_effects=True)
    request = FunctionCallRequest(
        function="ouroboros.entry.mark_archived",
        actor=ActorContext(actor_id=str(actor_id), session_id="s-1"),
        target=TargetRef(kind="global"),
        payload={"all_reviewed": True},
    )
    denied = check_dispatch_permission(conn, entry, request)
    assert denied.error is not None
    assert "could not resolve a target project" in (
        denied.error.error.message if denied.error.error else ""
    )