"""Registry schema, validation, publication, and pinning tests."""

from __future__ import annotations

from copy import deepcopy

import pytest

from yoke_core.domain.builtin_workflow_definitions import (
    BUILTIN_WORKFLOW_IDS,
    builtin_workflow_definition,
    builtin_workflow_definitions,
)
from yoke_core.domain.workflow_definition_validation import (
    WorkflowDefinitionError,
    validate_workflow_definition,
)
from yoke_core.domain.workflow_registry import (
    WorkflowRegistryError,
    list_current_workflows,
    publish_workflow_version,
    resolve_current_workflow_pin,
    set_current_workflow_version,
)


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
    for binding in definition["executor_bindings"]:
        for key in ("from_stage_id", "through_stage_id"):
            if binding[key] == before:
                binding[key] = after


def test_schema_boot_seeds_immutable_builtin_versions(test_db):
    workflows = list_current_workflows(test_db)
    assert {row["id"] for row in workflows} == set(BUILTIN_WORKFLOW_IDS)
    assert {row["current_version"] for row in workflows} == {1}
    assert all(row["current_version_id"] for row in workflows)
    assert all(len(row["versions"]) == 1 for row in workflows)
    assert all(row["definition_digest"] for row in workflows)


@pytest.mark.parametrize(
    "mutate, match",
    [
        (
            lambda value: value["stages"][0]["gates"].append(
                {"id": "unknown_gate"}
            ),
            "unknown gate",
        ),
        (
            lambda value: value["executor_bindings"][0].update(
                executor_id="unknown_executor"
            ),
            "unknown executor",
        ),
        (
            lambda value: value["stages"][1].update(
                label=value["stages"][0]["label"]
            ),
            "labels must be unique",
        ),
        (
            lambda value: value.update(terminal_stage_ids=["missing"]),
            "terminal_stage_ids",
        ),
        (
            lambda value: value["policies"].update(
                governed_migrations="optional"
            ),
            "core invariants",
        ),
        (
            lambda value: value["transitions"].pop(),
            "no outgoing transition",
        ),
    ],
)
def test_invalid_definitions_fail_closed(mutate, match):
    definition = _definition()
    mutate(definition)
    with pytest.raises(WorkflowDefinitionError, match=match):
        validate_workflow_definition(definition)


def test_structural_stage_change_requires_complete_mapping():
    previous = _definition()
    changed = deepcopy(previous)
    _replace_stage_id(changed, "release", "delivering")

    with pytest.raises(WorkflowDefinitionError, match="stage_mapping"):
        validate_workflow_definition(changed, previous=previous)

    changed["stage_mapping"] = {
        stage["id"]: (
            "delivering" if stage["id"] == "release" else stage["id"]
        )
        for stage in previous["stages"]
    }
    validate_workflow_definition(changed, previous=previous)


def test_published_rows_reject_update_and_delete(test_db):
    row = test_db.execute(
        "SELECT id FROM workflow_versions ORDER BY id LIMIT 1"
    ).fetchone()
    version_id = int(row[0])
    with pytest.raises(Exception, match="immutable"):
        test_db.execute(
            "UPDATE workflow_versions SET definition_digest = 'changed' "
            "WHERE id = %s",
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
    workflow_id, version_one_id = resolve_current_workflow_pin(test_db, "issue")
    test_db.execute(
        "INSERT INTO items "
        "(id, title, status, priority, created_at, updated_at, "
        "project_id, project_sequence, workflow_id, workflow_version_id) "
        "VALUES (901, 'Pinned', 'idea', 'medium', "
        "'2026-07-25T00:00:00Z', '2026-07-25T00:00:00Z', 1, 901, %s, %s)",
        (workflow_id, version_one_id),
    )
    test_db.commit()

    next_definition = _definition()
    next_definition["stages"][0]["label"] = "Filed"
    published = publish_workflow_version(
        test_db,
        workflow_id="issue",
        definition=next_definition,
    )
    assert published["version"] == 2
    assert resolve_current_workflow_pin(test_db, "issue") == (
        "issue",
        published["version_id"],
    )
    pinned = test_db.execute(
        "SELECT workflow_version_id FROM items WHERE id = 901"
    ).fetchone()
    assert int(pinned[0]) == version_one_id

    rolled_back = set_current_workflow_version(
        test_db,
        workflow_id="issue",
        version=1,
    )
    assert rolled_back["version_id"] == version_one_id
    assert resolve_current_workflow_pin(test_db, "issue") == (
        "issue",
        version_one_id,
    )


def test_publication_refuses_noop_definition(test_db):
    with pytest.raises(WorkflowRegistryError, match="must change"):
        publish_workflow_version(
            test_db,
            workflow_id="issue",
            definition=_definition(),
        )


def test_every_fixture_validates_as_a_first_publication():
    for fixture in builtin_workflow_definitions():
        validate_workflow_definition(fixture["definition"])
