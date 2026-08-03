"""Registry schema, validation, publication, and pinning tests."""

from __future__ import annotations

import sqlite3

import pytest

from runtime.api.fixtures.backlog_inserts import insert_item
from yoke_core.domain import builtin_workflow_version_convergence, db_helpers
from yoke_core.domain.builtin_workflow_definitions import (
    BUILTIN_WORKFLOW_IDS,
    builtin_workflow_definition,
    builtin_workflow_version_history,
)
from yoke_core.domain.workflow_definition_codec import (
    canonical_definition_json,
    definition_digest,
)
from yoke_core.domain.workflow_registry import (
    WorkflowRegistryError,
    converge_builtin_workflows,
    get_workflow_version,
    list_current_workflows,
    publish_workflow_version,
    resolve_current_workflow_pin,
    select_current_builtin_workflow_versions,
    set_current_workflow_version,
)
from yoke_core.domain.workflow_schema import ensure_workflow_registry_tables
from yoke_core.domain.workflow_policy_defaults import (
    publish_workflow_policy_defaults,
)
from yoke_core.domain.workflow_item_versioning import (
    inspect_item_workflow_pin,
    migrate_item_workflow_pin,
)

_TS = "2026-07-25T00:00:00Z"


def _definition(workflow_id: str = "issue") -> dict:
    return builtin_workflow_definition(workflow_id)["definition"]


def _replace_stage_id(definition: dict, before: str, after: str) -> None:
    for stage in definition["stages"]:
        if stage["id"] == before:
            stage["id"] = after
    definition["terminal_stage_ids"] = [
        after if value == before else value
        for value in definition["terminal_stage_ids"]
    ]
    for transition in definition["transitions"]:
        for key in ("from_stage_id", "to_stage_id"):
            if transition[key] == before:
                transition[key] = after
    for binding in definition["skill_bindings"]:
        for key in ("from_stage_id", "through_stage_id"):
            if binding[key] == before:
                binding[key] = after


def _reset_to_version_one(conn, fixtures) -> None:
    conn.execute("TRUNCATE workflows, workflow_versions RESTART IDENTITY CASCADE")
    selected = [
        fixture for fixture in fixtures if int(fixture["version"]) == 1
    ] or list(fixtures)
    for fixture in selected:
        workflow = fixture["workflow"]
        definition = fixture["definition"]
        workflow_values = tuple(
            workflow[key] for key in ("id", "name", "description", "source")
        )
        conn.execute(
            "INSERT INTO workflows "
            "(id, name, description, source, status, created_at, updated_at) "
            "VALUES (%s, %s, %s, %s, 'active', %s, %s)",
            workflow_values + (_TS, _TS),
        )
        version_id = conn.execute(
            "INSERT INTO workflow_versions "
            "(workflow_id, version, definition_schema_version, "
            "definition_json, definition_digest, published_at, immutable_at) "
            "VALUES (%s, 1, 1, %s, %s, %s, %s) RETURNING id",
            (workflow["id"], canonical_definition_json(definition),
             definition_digest(definition), _TS, _TS),
        ).fetchone()[0]
        conn.execute(
            "UPDATE workflows SET current_version_id = %s WHERE id = %s",
            (version_id, workflow["id"]),
        )
    conn.commit()


def _version_one_rows(conn) -> list[tuple]:
    rows = conn.execute(
        "SELECT workflow_id, definition_json, definition_digest "
        "FROM workflow_versions WHERE version = 1 ORDER BY workflow_id"
    ).fetchall()
    return [tuple(row.values()) for row in rows]


def test_known_version_one_definitions_converge_without_rewriting(
    test_db,
):
    _reset_to_version_one(test_db, builtin_workflow_version_history())
    expected_dash = builtin_workflow_definition("dash")["workflow"]
    test_db.execute(
        "UPDATE workflows SET name = 'Old', description = 'Old' "
        "WHERE id = 'dash'"
    )
    before = _version_one_rows(test_db)

    converge_builtin_workflows(test_db)

    assert _version_one_rows(test_db) == before
    dash_copy = test_db.execute(
        "SELECT name, description FROM workflows WHERE id = 'dash'"
    ).fetchone()
    assert tuple(dash_copy) == (expected_dash["name"], expected_dash["description"])
    workflows = list_current_workflows(test_db)
    assert {row["current_version"] for row in workflows} == {1}
    assert all(
        [version["version"] for version in row["versions"]] == [1, 2, 3]
        for row in workflows
    )

    selected = select_current_builtin_workflow_versions(test_db)
    assert set(selected.values()) == {3}
    assert {
        row["current_version"] for row in list_current_workflows(test_db)
    } == {3}


def test_unknown_version_one_definition_is_rejected(test_db):
    fixtures = builtin_workflow_version_history()
    fixtures[0]["definition"]["stages"][0]["label"] = "Unknown drift"
    _reset_to_version_one(test_db, fixtures)

    with pytest.raises(WorkflowRegistryError, match="issue@1 differs"):
        converge_builtin_workflows(test_db)
    test_db.rollback()


def test_builtin_convergence_keeps_sqlite_locking_portable():
    with sqlite3.connect(":memory:") as conn:
        conn.row_factory = sqlite3.Row
        ensure_workflow_registry_tables(conn)
        converge_builtin_workflows(conn)
        converge_builtin_workflows(conn)
        assert {
            (row["id"], row["current_version"], len(row["versions"]))
            for row in list_current_workflows(conn)
        } == {(workflow_id, 3, 3) for workflow_id in BUILTIN_WORKFLOW_IDS}


def test_selection_locks_before_digest_lookup(test_db, monkeypatch):
    def unexpected_lookup(*_args, **_kwargs):
        raise AssertionError("digest lookup ran before the workflow lock")

    monkeypatch.setattr(
        builtin_workflow_version_convergence,
        "_matching_version",
        unexpected_lookup,
    )
    test_db.execute("SELECT id FROM workflows WHERE id = 'issue' FOR UPDATE")
    with db_helpers.connect() as contender:
        contender.execute("SET LOCAL lock_timeout = '100ms'")
        with pytest.raises(Exception, match="lock timeout"):
            select_current_builtin_workflow_versions(contender)
        contender.rollback()
    test_db.rollback()


def test_fixed_history_rejects_operator_version_collision(test_db):
    _reset_to_version_one(test_db, builtin_workflow_version_history())
    changed = _definition()
    changed["stages"][0]["label"] = "Operator filed"
    assert publish_workflow_version(
        test_db,
        workflow_id="issue",
        definition=changed,
        published_by_actor_id=1,
    )["version"] == 2

    with pytest.raises(WorkflowRegistryError, match="issue@2 differs"):
        converge_builtin_workflows(test_db)
    test_db.rollback()


def test_published_rows_reject_update_and_delete(test_db):
    row = test_db.execute(
        "SELECT id FROM workflow_versions ORDER BY id LIMIT 1"
    ).fetchone()
    version_id = int(row[0])
    with pytest.raises(Exception, match="immutable"):
        test_db.execute(
            "UPDATE workflow_versions SET definition_digest = 'changed' WHERE id = %s",
            (version_id,),
        )
    test_db.rollback()
    with pytest.raises(Exception, match="immutable"):
        test_db.execute(
            "DELETE FROM workflow_versions WHERE id = %s",
            (version_id,),
        )
    test_db.rollback()


def test_publish_pins_existing_items_and_can_roll_back_new_item_default(test_db):
    _, builtin_version_id = resolve_current_workflow_pin(test_db, "issue")
    insert_item(test_db, id=901, title="Pinned")
    next_definition = _definition()
    next_definition["stages"][0]["label"] = "Filed"
    published = publish_workflow_version(
        test_db, workflow_id="issue", definition=next_definition,
    )
    assert published["version"] == 4
    assert resolve_current_workflow_pin(test_db, "issue") == (
        "issue", published["version_id"])
    pinned = test_db.execute(
        "SELECT workflow_version_id FROM items WHERE id = 901"
    ).fetchone()
    assert int(pinned[0]) == builtin_version_id
    rolled_back = set_current_workflow_version(
        test_db, workflow_id="issue", version=3,
    )
    assert rolled_back["version_id"] == builtin_version_id
    assert resolve_current_workflow_pin(test_db, "issue") == (
        "issue", builtin_version_id,
    )


def test_version_read_and_current_selection_use_optimistic_version(test_db):
    changed = _definition()
    changed["stages"][0]["label"] = "Filed"
    publish_workflow_version(test_db, workflow_id="issue", definition=changed)
    current_builtin = get_workflow_version(test_db, workflow_id="issue", version=3)
    assert current_builtin["current"] is False
    assert current_builtin["definition"]["stages"][0]["label"] == "idea"

    with pytest.raises(WorkflowRegistryError, match="refresh first"):
        set_current_workflow_version(
            test_db, workflow_id="issue", version=3, expected_current_version=3,
        )
    selected = set_current_workflow_version(
        test_db, workflow_id="issue", version=3, expected_current_version=4,
    )
    assert selected["version"] == 3


def test_editable_path_claim_default_publishes_an_immutable_version(test_db):
    result = publish_workflow_policy_defaults(
        test_db,
        workflow_id="dash",
        expected_current_version=3,
        path_claims_default=True,
        published_by_actor_id=1,
    )
    assert result["version"] == 4
    assert result["path_claims_default"] is True
    third = get_workflow_version(test_db, workflow_id="dash", version=3)
    fourth = get_workflow_version(test_db, workflow_id="dash", version=4)
    assert third["definition"]["policies"]["path_claims"] == "optional"
    assert fourth["definition"]["policies"]["path_claims"] == "required"
    assert fourth["current"] is True

    with pytest.raises(WorkflowRegistryError, match="refresh first"):
        publish_workflow_policy_defaults(
            test_db,
            workflow_id="dash",
            expected_current_version=3,
            path_claims_default=False,
        )
    with pytest.raises(WorkflowRegistryError, match="does not expose"):
        publish_workflow_policy_defaults(
            test_db,
            workflow_id="issue",
            expected_current_version=3,
            path_claims_default=False,
        )


def test_current_definition_change_does_not_repin_existing_item(test_db):
    _, builtin_version_id = resolve_current_workflow_pin(test_db, "issue")
    insert_item(test_db, id=902, title="Stable pin")
    next_definition = _definition()
    next_definition["stages"][0]["label"] = "Submitted"
    published = publish_workflow_version(
        test_db, workflow_id="issue", definition=next_definition,
    )
    pinned = inspect_item_workflow_pin(test_db, 902)
    assert pinned["workflow_version"] == 3
    assert pinned["workflow_version_id"] == builtin_version_id
    assert pinned["status"] == "idea"

    migrated = migrate_item_workflow_pin(test_db, item_id=902)
    assert migrated["changed"] is True
    assert migrated["after"]["workflow_version"] == 4
    assert migrated["after"]["workflow_version_id"] == published["version_id"]


def test_compatible_item_migration_applies_adjacent_stage_mapping(test_db):
    insert_item(test_db, id=903, title="Mapped pin", status="release")
    changed = _definition()
    _replace_stage_id(changed, "release", "delivering")
    changed["stage_mapping"] = {
        stage["id"]: ("delivering" if stage["id"] == "release" else stage["id"])
        for stage in _definition()["stages"]
    }
    publish_workflow_version(test_db, workflow_id="issue", definition=changed)
    migrated = migrate_item_workflow_pin(test_db, item_id=903)
    assert migrated["after"]["status"] == "delivering"
    assert migrated["after"]["workflow_version"] == 4


def test_publication_refuses_noop_definition(test_db):
    with pytest.raises(WorkflowRegistryError, match="must change"):
        publish_workflow_version(test_db, workflow_id="issue", definition=_definition())
