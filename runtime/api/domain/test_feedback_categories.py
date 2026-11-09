"""Stored feedback data, category convergence and visibility."""

from runtime.api.fixtures.actor_roles import seed_org_role

import pytest

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain.handlers.ouroboros_reads import handle_ouroboros_entry_list
from yoke_core.domain.ouroboros_entry_insert import cmd_insert_entry
from runtime.api.domain.ouroboros_https_permissions_test_support import _project_owner


def insert(conn, category="observation", project=None):
    return int(
        cmd_insert_entry(
            conn,
            "2026-01-01T00:00:00Z",
            "engineer",
            category,
            "Concrete evidence",
            project,
            reporter_email="reporter@example.test",
            yoke_version="0.2.0.202610290013",
            universe_fingerprint="fixture@2026-01-01T00:00:00Z",
        )
    )


def read(actor, **payload):
    request = FunctionCallRequest(
        function="ouroboros.field_note.list",
        actor=ActorContext(actor_id=str(actor), session_id="fixture"),
        target=TargetRef(kind="global"),
        payload=payload,
    )
    outcome = handle_ouroboros_entry_list(request)
    assert outcome.primary_success, outcome.error
    return {row["id"] for row in outcome.result_payload["entries"]}


@pytest.mark.parametrize(
    "category", ["failed", "new", "unclear", "observation", "idea"]
)
def test_writer_stores_one_category_and_attribution(test_db, category):
    entry = insert(test_db, category)
    row = test_db.execute(
        "SELECT category,body,project_id,agent,reporter_email FROM ouroboros_entries WHERE id=%s",
        (entry,),
    ).fetchone()
    assert tuple(row) == (
        category,
        "Concrete evidence",
        None,
        "engineer",
        "reporter@example.test",
    )


def test_invalid_category_writes_nothing(test_db):
    before = test_db.execute("SELECT COUNT(*) FROM ouroboros_entries").fetchone()[0]
    with pytest.raises(ValueError, match="feedback_category_invalid"):
        insert(test_db, "problem")
    assert (
        test_db.execute("SELECT COUNT(*) FROM ouroboros_entries").fetchone()[0]
        == before
    )


@pytest.mark.parametrize("shape", [None, "roster"])
def test_scope_respects_admin_and_project_visibility(test_db, shape):
    member = _project_owner(test_db, "yoke")
    admin = _project_owner(test_db, "yoke")
    org = test_db.execute("SELECT org_id FROM projects WHERE slug='yoke'").fetchone()[0]
    seed_org_role(test_db, actor_id=admin, org_id=org, role_name="admin")
    scoped, unscoped = insert(test_db, project="yoke"), insert(test_db)
    options = {"shape": shape} if shape else {}
    assert read(admin, **options) == {scoped, unscoped}
    assert read(admin, scope="project", project="yoke", **options) == {scoped}
    assert read(admin, scope="unscoped", **options) == {unscoped}
    assert read(member, **options) == {scoped}
    assert read(member, scope="unscoped", **options) == set()


@pytest.mark.parametrize(
    "function,column",
    [
        ("ouroboros.entry.mark_reviewed", "reviewed_at"),
        ("ouroboros.entry.mark_archived", "archived_at"),
    ],
)
def test_only_admin_can_curate_unscoped_note_without_a_project_hint(
    test_db, function, column
):
    from runtime.api.domain.yoke_function_permissions_test_support import _entry
    from yoke_core.domain.yoke_function_permissions import check_dispatch_permission
    from yoke_core.domain.handlers import ouroboros_writes
    from yoke_core.domain.actor_permissions import PERM_EVENTS_WRITE

    member = _project_owner(test_db, "yoke")
    admin = _project_owner(test_db, "yoke")
    org = test_db.execute("SELECT org_id FROM projects WHERE slug='yoke'").fetchone()[0]
    seed_org_role(test_db, actor_id=admin, org_id=org, role_name="admin")
    entry_id = insert(test_db)
    request = FunctionCallRequest(
        function=function,
        actor=ActorContext(actor_id=str(member), session_id="fixture"),
        target=TargetRef(kind="global"),
        payload={"entry_id": entry_id, "project": "yoke"},
    )
    assert (
        check_dispatch_permission(test_db, _entry(function), request).error is not None
    )
    request.actor.actor_id = str(admin)
    request.payload.pop("project")
    permission = check_dispatch_permission(test_db, _entry(function), request)
    assert permission.error is None
    assert permission.permission_key == PERM_EVENTS_WRITE
    handler = (
        ouroboros_writes.handle_ouroboros_entry_mark_reviewed
        if column == "reviewed_at"
        else ouroboros_writes.handle_ouroboros_entry_mark_archived
    )
    assert handler(request).primary_success
    assert (
        test_db.execute(
            f"SELECT {column} FROM ouroboros_entries WHERE id=%s", (entry_id,)
        ).fetchone()[0]
        is not None
    )
