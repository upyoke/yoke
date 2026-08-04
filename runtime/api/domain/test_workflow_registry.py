"""Registry schema, validation, publication, and pinning tests."""

from __future__ import annotations

import pytest

from runtime.api.fixtures.backlog_inserts import insert_item
from runtime.api.workflow_version_test_helpers import current_workflow_version
from yoke_core.domain.builtin_workflow_definitions import (
    builtin_workflow_definition,
)
from yoke_core.domain.workflow_definition_codec import (
    canonical_definition_json,
    definition_digest,
)
from yoke_core.domain.workflow_registry import (
    WorkflowRegistryError,
    get_workflow_version,
    publish_workflow_version,
    resolve_current_workflow_pin,
    set_current_workflow_version,
)
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
        fixture for fixture in fixtures if int(fixture["canon_version"]) == 1
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
    current = current_workflow_version(test_db, "issue")
    _, builtin_version_id = resolve_current_workflow_pin(test_db, "issue")
    insert_item(test_db, id=901, title="Pinned")
    next_definition = _definition()
    next_definition["stages"][0]["label"] = "Filed"
    published = publish_workflow_version(
        test_db, workflow_id="issue", definition=next_definition,
    )
    assert published["version"] == current + 1
    assert resolve_current_workflow_pin(test_db, "issue") == (
        "issue", published["version_id"])
    pinned = test_db.execute(
        "SELECT workflow_version_id FROM items WHERE id = 901"
    ).fetchone()
    assert int(pinned[0]) == builtin_version_id
    rolled_back = set_current_workflow_version(
        test_db, workflow_id="issue", version=current,
    )
    assert rolled_back["version_id"] == builtin_version_id
    assert resolve_current_workflow_pin(test_db, "issue") == (
        "issue", builtin_version_id,
    )


def test_version_read_and_current_selection_use_optimistic_version(test_db):
    current = current_workflow_version(test_db, "issue")
    changed = _definition()
    changed["stages"][0]["label"] = "Filed"
    publish_workflow_version(test_db, workflow_id="issue", definition=changed)
    current_builtin = get_workflow_version(
        test_db, workflow_id="issue", version=current
    )
    assert current_builtin["current"] is False
    assert current_builtin["definition"]["stages"][0]["label"] == "idea"

    with pytest.raises(WorkflowRegistryError, match="refresh first"):
        set_current_workflow_version(
            test_db,
            workflow_id="issue",
            version=current,
            expected_current_version=current,
        )
    selected = set_current_workflow_version(
        test_db,
        workflow_id="issue",
        version=current,
        expected_current_version=current + 1,
    )
    assert selected["version"] == current


def test_editable_path_claim_default_publishes_an_immutable_version(test_db):
    current = current_workflow_version(test_db, "dash")
    result = publish_workflow_policy_defaults(
        test_db,
        workflow_id="dash",
        expected_current_version=current,
        path_claims_default=True,
        published_by_actor_id=1,
    )
    assert result["version"] == current + 1
    assert result["path_claims_default"] is True
    previous = get_workflow_version(
        test_db, workflow_id="dash", version=current
    )
    published = get_workflow_version(
        test_db, workflow_id="dash", version=current + 1
    )
    assert previous["definition"]["policies"]["path_claims"] == "optional"
    assert published["definition"]["policies"]["path_claims"] == "required"
    assert published["current"] is True

    with pytest.raises(WorkflowRegistryError, match="refresh first"):
        publish_workflow_policy_defaults(
            test_db,
            workflow_id="dash",
            expected_current_version=current,
            path_claims_default=False,
        )
    with pytest.raises(WorkflowRegistryError, match="does not expose"):
        publish_workflow_policy_defaults(
            test_db,
            workflow_id="issue",
            expected_current_version=current,
            path_claims_default=False,
        )


def test_current_definition_change_does_not_repin_existing_item(test_db):
    current = current_workflow_version(test_db, "issue")
    _, builtin_version_id = resolve_current_workflow_pin(test_db, "issue")
    insert_item(test_db, id=902, title="Stable pin")
    next_definition = _definition()
    next_definition["stages"][0]["label"] = "Submitted"
    published = publish_workflow_version(
        test_db, workflow_id="issue", definition=next_definition,
    )
    pinned = inspect_item_workflow_pin(test_db, 902)
    assert pinned["workflow_version"] == current
    assert pinned["workflow_version_id"] == builtin_version_id
    assert pinned["status"] == "idea"

    migrated = migrate_item_workflow_pin(test_db, item_id=902)
    assert migrated["changed"] is True
    assert migrated["after"]["workflow_version"] == current + 1
    assert migrated["after"]["workflow_version_id"] == published["version_id"]


def test_compatible_item_migration_applies_adjacent_stage_mapping(test_db):
    current = current_workflow_version(test_db, "issue")
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
    assert migrated["after"]["workflow_version"] == current + 1


def test_publication_refuses_noop_definition(test_db):
    with pytest.raises(WorkflowRegistryError, match="must change"):
        publish_workflow_version(test_db, workflow_id="issue", definition=_definition())
