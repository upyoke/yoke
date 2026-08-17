"""Migration compatibility for QA requirements without stage linkage.

Requirements that predate ``workflow_transition_id`` are enforced at
runtime by phase at the ``qa_verification`` anchor stage, so migration
maps them through that anchor instead of refusing the missing linkage,
and waived requirements impose no compatibility constraint at all.
"""

from __future__ import annotations

from copy import deepcopy

import pytest

from runtime.api.fixtures.backlog import insert_item, insert_qa_requirement
from yoke_core.domain.builtin_workflow_definitions import (
    builtin_workflow_definition,
)
from yoke_core.domain.db_helpers import iso8601_now
from yoke_core.domain.workflow_definition_codec import WorkflowRegistryError
from yoke_core.domain.workflow_item_versioning import migrate_item_workflow_pin
from yoke_core.domain.workflow_registry import publish_workflow_version


ITEM_ID = 951


def _strip_qa_gates(definition: dict, stage_ids: tuple[str, ...]) -> None:
    for stage in definition["stages"]:
        if stage["id"] in stage_ids:
            stage["gates"] = [
                gate for gate in stage["gates"] if gate["id"] != "qa_verification"
            ]


def _publish_pair(
    test_db,
    *,
    strip_target_stages: tuple[str, ...] = (),
) -> tuple[dict, dict]:
    source_definition = deepcopy(builtin_workflow_definition("issue")["definition"])
    source_definition["stages"][0]["label"] = "Phase anchor source"
    source = publish_workflow_version(
        test_db,
        workflow_id="issue",
        definition=source_definition,
    )
    insert_item(
        test_db,
        id=ITEM_ID,
        workflow_id="issue",
        status="implementing",
    )
    target_definition = deepcopy(source_definition)
    target_definition["stages"][0]["label"] = "Phase anchor target"
    if strip_target_stages:
        _strip_qa_gates(target_definition, strip_target_stages)
    target = publish_workflow_version(
        test_db,
        workflow_id="issue",
        definition=target_definition,
    )
    return source, target


def _migrate(test_db, target: dict) -> dict:
    return migrate_item_workflow_pin(
        test_db,
        item_id=ITEM_ID,
        target_version=int(target["version"]),
    )


def test_unlinked_requirements_migrate_when_enforcement_matches(test_db):
    source, target = _publish_pair(test_db)
    insert_qa_requirement(test_db, item_id=ITEM_ID, qa_phase="verification")
    insert_qa_requirement(test_db, item_id=ITEM_ID, qa_phase="post_deploy")

    result = _migrate(test_db, target)

    assert result["changed"] is True
    assert result["before"]["workflow_version_id"] == source["version_id"]
    assert result["after"]["workflow_version_id"] == target["version_id"]


def test_unlinked_requirement_blocks_when_target_moves_anchor(test_db):
    _source, target = _publish_pair(
        test_db,
        strip_target_stages=("reviewed-implementation",),
    )
    insert_qa_requirement(test_db, item_id=ITEM_ID)

    with pytest.raises(WorkflowRegistryError) as raised:
        _migrate(test_db, target)

    message = str(raised.value)
    assert "source anchor stage 'reviewed-implementation'" in message
    assert "target anchor stage 'implemented'" in message
    assert "yoke qa requirement waive" in message
    assert "accept the current workflow pin" in message


def test_unlinked_requirement_blocks_when_target_drops_all_qa_gates(test_db):
    _source, target = _publish_pair(
        test_db,
        strip_target_stages=(
            "reviewed-implementation",
            "implemented",
            "release",
            "done",
        ),
    )
    insert_qa_requirement(test_db, item_id=ITEM_ID)

    with pytest.raises(WorkflowRegistryError) as raised:
        _migrate(test_db, target)

    message = str(raised.value)
    assert "source anchor stage 'reviewed-implementation'" in message
    assert "target anchor stage <none>" in message
    assert "--source operator --force" in message


def test_waived_unlinked_requirement_never_blocks(test_db):
    _source, target = _publish_pair(
        test_db,
        strip_target_stages=("reviewed-implementation", "implemented", "release"),
    )
    insert_qa_requirement(test_db, item_id=ITEM_ID, waived_at=iso8601_now())

    assert _migrate(test_db, target)["changed"] is True


def test_waived_linked_requirement_never_blocks(test_db):
    _source, target = _publish_pair(
        test_db,
        strip_target_stages=("reviewed-implementation", "implemented", "release"),
    )
    insert_qa_requirement(
        test_db,
        item_id=ITEM_ID,
        workflow_transition_id="reviewed-implementation",
        waived_at=iso8601_now(),
    )

    assert _migrate(test_db, target)["changed"] is True
