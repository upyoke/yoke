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

from runtime.api.domain.function_authz_scope_routing_test_support import (
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
            
            category="observation",
            body="note carries project",
            project="yoke",
        yoke_version="0.2.0.202610290013", universe_fingerprint="fixture@2026-01-01T00:00:00Z")
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


@pytest.mark.parametrize("function", ["merge.audit.snapshot"])
def test_agent_capture_and_merge_snapshot_enforce_target_project(conn, function):
    from yoke_contracts.api.function_call import TargetRef

    allowed_project = resolve_project_id(conn, "externalwebapp")
    denied_project = resolve_project_id(conn, "yoke")
    actor = _project_owner(conn, allowed_project)
    for project, allowed in ((allowed_project, True), (denied_project, False)):
        request = _payload_request(actor, function, {}).model_copy(
            update={
                "target": TargetRef(kind="global", project_id=str(project)),
            }
        )
        permission = check_dispatch_permission(conn, _entry(function), request)
        assert (permission.error is None) is allowed


def test_session_ci_wait_writes_are_actor_session() -> None:
    record = PRODUCT_AUTHZ_BY_ID["session_ci_wait.record"]
    resolve = PRODUCT_AUTHZ_BY_ID["session_ci_wait.resolve"]

    assert record.scope == ACTOR_SESSION
    assert resolve.scope == ACTOR_SESSION
    assert record.permission_key is None
    assert resolve.permission_key is None


def test_merge_queue_marker_writes_use_project_item_write_authority() -> None:
    mark = PRODUCT_AUTHZ_BY_ID["merge_queue.landing_pending.mark"]
    clear = PRODUCT_AUTHZ_BY_ID["merge_queue.landing_pending.clear"]
    observe = PRODUCT_AUTHZ_BY_ID["merge_queue.landing.observe"]

    assert mark == clear == observe
    assert mark.permission_key == "items.write"


def _item_in(conn, item_id: int, project_id: int) -> None:
    from yoke_core.domain.workflow_registry import converge_builtin_workflows

    converge_builtin_workflows(conn)
    conn.execute(
        "INSERT INTO items (id, title, workflow_id, workflow_version_id, status, "
        "created_at, updated_at, project_id, project_sequence) VALUES (%s, 't', "
        "'dash', (SELECT current_version_id FROM workflows WHERE id='dash'), 'idea', "
        "'2026-11-19T00:00:00Z', '2026-11-19T00:00:00Z', %s, %s)",
        (item_id, project_id, item_id),
    )
    conn.commit()


def test_delivery_clearance_is_a_project_read_the_mechanics_reads_are_not(conn):
    """A member holding only items.read on the item's project may ask its
    delivery clearance; the org-admin reads it replaced stay denied, and a
    caller without access to the item's project is denied the new read."""
    from yoke_contracts.api.function_call import (
        ActorContext,
        FunctionCallRequest,
        TargetRef,
    )
    from yoke_core.domain.actor_permissions import ROLE_VIEWER

    from runtime.api.domain.function_authz_scope_routing_test_support import (
        _new_actor,
    )
    from runtime.api.fixtures.actor_roles import seed_project_role

    member_project = resolve_project_id(conn, "externalwebapp")
    other_project = resolve_project_id(conn, "yoke")
    actor = _new_actor(conn)
    seed_project_role(
        conn,
        actor_id=actor,
        project_id=member_project,
        role_name=ROLE_VIEWER,
        granted_by_actor_id=actor,
    )
    _item_in(conn, 7101, member_project)
    _item_in(conn, 7102, other_project)

    def check(function: str, target: TargetRef):
        request = FunctionCallRequest(
            function=function,
            actor=ActorContext(actor_id=str(actor), session_id="s-1"),
            target=target,
            payload={},
        )
        return check_dispatch_permission(
            conn, _entry(function, side_effects=False), request
        )

    clearance = "done_transition.delivery_clearance"
    assert PRODUCT_AUTHZ_BY_ID[clearance].permission_key == "items.read"
    own = check(clearance, TargetRef(kind="item", item_id=7101))
    assert own.error is None
    assert own.project_id == member_project
    assert check(clearance, TargetRef(kind="item", item_id=7102)).error is not None
    for admin_read in ("workflows.mechanics.get", "deployment_flows.get"):
        assert check(admin_read, TargetRef(kind="global")).error is not None
