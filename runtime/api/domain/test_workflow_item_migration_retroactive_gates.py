"""Retroactive gate rejection for item workflow migration."""

from __future__ import annotations

import pytest

from runtime.api.domain.test_workflow_item_migration_compatibility import (
    ITEM_ID,
    _pin,
    _publish_pair,
)
from yoke_core.domain.workflow_definition_codec import WorkflowRegistryError
from yoke_core.domain.workflow_item_versioning import (
    migrate_item_workflow_pin,
)


@pytest.mark.parametrize(
    ("case", "message"),
    (
        ("reached_approval", "unsatisfied approval"),
        ("reached_qa", "unsatisfied QA gate"),
    ),
)
def test_retroactive_gate_without_binding_rejects_migration(
    test_db,
    case: str,
    message: str,
):
    _source, target = _publish_pair(test_db, case=case)
    before = _pin(test_db)

    with pytest.raises(WorkflowRegistryError, match=message):
        migrate_item_workflow_pin(
            test_db,
            item_id=ITEM_ID,
            target_version=int(target["version"]),
        )

    assert _pin(test_db) == before


@pytest.mark.parametrize(
    ("has_old_gate", "keeps_old_gate", "extra_gate", "allowed"),
    [(True, False, False, True), (False, False, False, False),
     (True, True, False, False), (True, False, True, False)],
)
def test_only_the_prose_gate_replacement_preserves_reached_admission(
    test_db, has_old_gate, keeps_old_gate, extra_gate, allowed,
):
    from copy import deepcopy
    from runtime.api.fixtures.backlog import insert_item
    from yoke_core.domain.builtin_workflow_definitions import builtin_workflow_definition
    from yoke_core.domain.workflow_registry import publish_workflow_version

    source_definition = deepcopy(builtin_workflow_definition("dash")["definition"])
    source_definition["stages"][0]["label"] = "Source pin"
    review = next(s for s in source_definition["stages"] if s["id"] == "reviewing-implementation")
    review["gates"] = [g for g in review["gates"] if g["id"] != "new_migrations_need_db_claim"]
    if has_old_gate:
        review["gates"].append({"id": "db_claim_prose"})
    source = publish_workflow_version(test_db, workflow_id="dash", definition=source_definition)
    insert_item(test_db, id=ITEM_ID, workflow_id="dash", status="release")
    target_definition = deepcopy(source_definition)
    target_definition["stages"][0]["label"] = "Target pin"
    target_review = next(s for s in target_definition["stages"] if s["id"] == "reviewing-implementation")
    if not keeps_old_gate:
        target_review["gates"] = [g for g in target_review["gates"] if g["id"] != "db_claim_prose"]
    target_review["gates"].append({"id": "new_migrations_need_db_claim"})
    if extra_gate:
        target_review["gates"].append({"id": "conflict_survey"})
    target = publish_workflow_version(test_db, workflow_id="dash", definition=target_definition)
    if allowed:
        migrate_item_workflow_pin(test_db, item_id=ITEM_ID, target_version=target["version"])
        assert _pin(test_db) == (target["version_id"], "release")
    else:
        with pytest.raises(WorkflowRegistryError, match="unsatisfied .* gate"):
            migrate_item_workflow_pin(test_db, item_id=ITEM_ID, target_version=target["version"])
        assert _pin(test_db) == (source["version_id"], "release")
