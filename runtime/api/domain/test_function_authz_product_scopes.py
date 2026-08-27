"""Authorization routing for workflow-aware product surfaces."""

import pytest

from yoke_core.domain.actor_permissions import seed_roles_and_permissions
from yoke_core.domain.auth_schema import create_auth_tables
from yoke_core.domain.function_authz_product_scopes import PRODUCT_AUTHZ_BY_ID
from yoke_core.domain.function_authz_types import ACTOR_SESSION
from yoke_core.domain.org_schema import seed_default_org
from yoke_core.domain.project_identity import resolve_project_id
from yoke_core.domain.project_seed_test_helpers import seed_project_identities
from yoke_core.domain.schema_init_actor_path_claim_tables import (
    create_actor_path_claim_tables,
)
from yoke_core.domain.schema_init_path_tables import create_path_registry_tables
from yoke_core.domain.schema_init_tables import create_core_tables
from yoke_core.domain.yoke_function_permissions import check_dispatch_permission

from runtime.api.domain.test_function_authz_scope_routing import (
    _entry,
    _payload_request,
    _project_owner,
)
from runtime.api.fixtures import pg_testdb


@pytest.fixture
def conn():
    name = pg_testdb.create_test_database()
    connection = pg_testdb.drop_database_on_close(
        pg_testdb.connect_test_database(name),
        name,
    )
    create_core_tables(connection)
    seed_project_identities(connection)
    create_path_registry_tables(connection)
    create_actor_path_claim_tables(connection)
    create_auth_tables(connection)
    seed_default_org(connection)
    seed_roles_and_permissions(connection)
    yield connection
    connection.close()


def test_field_note_promotion_requires_write_access_to_payload_project(conn):
    yoke = resolve_project_id(conn, "yoke")
    externalwebapp = resolve_project_id(conn, "externalwebapp")
    actor_id = _project_owner(conn, externalwebapp)
    entry = _entry("ouroboros.field_note.promote")

    allowed = check_dispatch_permission(
        conn,
        entry,
        _payload_request(
            actor_id,
            "ouroboros.field_note.promote",
            {"project": "externalwebapp"},
        ),
    )
    assert allowed.error is None
    assert allowed.project_id == externalwebapp

    denied = check_dispatch_permission(
        conn,
        entry,
        _payload_request(
            actor_id,
            "ouroboros.field_note.promote",
            {"project": "yoke"},
        ),
    )
    assert denied.error is not None
    assert denied.project_id == yoke


def test_field_note_promotion_falls_back_to_note_project_without_flag(conn):
    from yoke_core.domain.ouroboros_entries import cmd_insert_entry

    yoke = resolve_project_id(conn, "yoke")
    actor_id = _project_owner(conn, yoke)
    entry_id = int(
        cmd_insert_entry(
            conn,
            timestamp="2026-08-10T18:03:05Z",
            agent="test",
            context=None,
            category="field-note-observation",
            body="note carries project",
            project="yoke",
        )
    )
    allowed = check_dispatch_permission(
        conn,
        _entry("ouroboros.field_note.promote"),
        _payload_request(
            actor_id,
            "ouroboros.field_note.promote",
            {"entry_id": entry_id, "title": "From note project"},
        ),
    )
    assert allowed.error is None
    assert allowed.project_id == yoke


def test_execution_instruction_resolve_is_an_authenticated_read() -> None:
    spec = PRODUCT_AUTHZ_BY_ID["workflow.execution_instruction.resolve"]

    assert spec.scope == ACTOR_SESSION
    assert spec.permission_key is None


def test_merge_queue_marker_writes_use_project_item_write_authority() -> None:
    mark = PRODUCT_AUTHZ_BY_ID["merge_queue.landing_pending.mark"]
    clear = PRODUCT_AUTHZ_BY_ID["merge_queue.landing_pending.clear"]

    assert mark == clear
    assert mark.permission_key == "items.write"
