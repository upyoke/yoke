"""Stored feedback data, category convergence and visibility."""

import importlib
import pytest

from yoke_contracts.api.function_call import ActorContext, FunctionCallRequest, TargetRef
from yoke_core.domain.handlers.ouroboros_reads import handle_ouroboros_entry_list
from yoke_core.domain.ouroboros_entry_insert import cmd_insert_entry
from runtime.api.domain.test_ouroboros_https_permissions import _project_owner
from yoke_core.domain.actor_permissions import grant_actor_org_role


def insert(conn, category="observation", project=None):
    return int(cmd_insert_entry(conn, "2026-01-01T00:00:00Z", "engineer", None,
                                category, "Concrete evidence", project,
                                reporter_email="reporter@example.test"))


def read(actor, **payload):
    request = FunctionCallRequest(function="ouroboros.field_note.list",
        actor=ActorContext(actor_id=str(actor), session_id="fixture"),
        target=TargetRef(kind="global"), payload=payload)
    outcome = handle_ouroboros_entry_list(request)
    assert outcome.primary_success, outcome.error
    return {row["id"] for row in outcome.result_payload["entries"]}


@pytest.mark.parametrize("category", ["failed", "new", "unclear", "observation", "idea"])
def test_writer_stores_one_category_and_attribution(test_db, category):
    entry = insert(test_db, category)
    row = test_db.execute("SELECT category,body,project_id,agent,reporter_email FROM ouroboros_entries WHERE id=%s", (entry,)).fetchone()
    assert tuple(row) == (category, "Concrete evidence", None, "engineer", "reporter@example.test")


def test_invalid_category_writes_nothing(test_db):
    before = test_db.execute("SELECT COUNT(*) FROM ouroboros_entries").fetchone()[0]
    with pytest.raises(ValueError, match="feedback_category_invalid"):
        insert(test_db, "problem")
    assert test_db.execute("SELECT COUNT(*) FROM ouroboros_entries").fetchone()[0] == before


def test_migration_maps_existing_notes_without_row_loss(test_db):
    migration = importlib.import_module("yoke_core.domain.migrations.0095_feedback_categories")
    prefix = "field" + "-note-"
    old = [prefix + "failed", prefix + "new", prefix + "unclear", prefix + "observation", "friction", "problem", "game-changing-idea", "critique", "pattern", "metric", "freeform", "unknown", "**"]
    expected = ["failed", "new", "unclear", "observation", "failed", "failed", "idea", *["observation"] * 6]
    for index, category in enumerate(old):
        test_db.execute("INSERT INTO ouroboros_entries (timestamp,agent,category,body,created_at) VALUES ('2026-01-01T00:00:00Z','tester',%s,%s,'2026-01-01T00:00:00Z')", (category, str(index)))
    migration.apply(test_db)
    migration.invariants(test_db)
    rows = test_db.execute("SELECT category FROM ouroboros_entries ORDER BY id").fetchall()
    assert [row[0] for row in rows] == expected
    test_db.execute("SAVEPOINT rejected_category")
    with pytest.raises(Exception, match="feedback_category_valid"):
        test_db.execute("UPDATE ouroboros_entries SET category='unknown'")
    test_db.execute("ROLLBACK TO SAVEPOINT rejected_category")
    assert test_db.execute("SELECT COUNT(*) FROM ouroboros_entries").fetchone()[0] == len(old)


@pytest.mark.parametrize("shape", [None, "roster"])
def test_scope_respects_admin_and_project_visibility(test_db, shape):
    member = _project_owner(test_db, "yoke")
    admin = _project_owner(test_db, "yoke")
    org = test_db.execute("SELECT org_id FROM projects WHERE slug='yoke'").fetchone()[0]
    grant_actor_org_role(test_db, actor_id=admin, org_id=org, role_name="admin")
    scoped, unscoped = insert(test_db, project="yoke"), insert(test_db)
    options = {"shape": shape} if shape else {}
    assert read(admin, **options) == {scoped, unscoped}
    assert read(admin, scope="project", project="yoke", **options) == {scoped}
    assert read(admin, scope="unscoped", **options) == {unscoped}
    assert read(member, **options) == {scoped}
    assert read(member, scope="unscoped", **options) == set()
