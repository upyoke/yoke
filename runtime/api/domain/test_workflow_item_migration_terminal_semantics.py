"""Workflow-version migration cannot terminate or resurrect an item."""

from __future__ import annotations

from copy import deepcopy

import pytest

from runtime.api.fixtures.backlog import insert_item
from runtime.api.workflow_version_test_helpers import (
    publish_issue_completion_stage,
)
from yoke_core.domain.builtin_workflow_definitions import (
    builtin_workflow_definition,
)
from yoke_core.domain.workflow_definition_codec import WorkflowRegistryError
from yoke_core.domain.workflow_item_versioning import (
    migrate_item_workflow_pin,
)
from yoke_core.domain.workflow_registry import publish_workflow_version


def _publish_release_terminal_version(conn) -> dict:
    definition = deepcopy(builtin_workflow_definition("issue")["definition"])
    previous_ids = [str(stage["id"]) for stage in definition["stages"]]
    definition["stages"] = [
        stage for stage in definition["stages"] if stage["id"] != "done"
    ]
    definition["terminal_stage_ids"] = ["release"]
    definition["transitions"] = [
        edge for edge in definition["transitions"] if edge["to_stage_id"] != "done"
    ]
    for binding in definition["executor_bindings"]:
        if binding["through_stage_id"] == "done":
            binding["through_stage_id"] = "release"
    definition["stage_mapping"] = {
        stage_id: "release" if stage_id == "done" else stage_id
        for stage_id in previous_ids
    }
    return publish_workflow_version(
        conn,
        workflow_id="issue",
        definition=definition,
    )


def test_migration_cannot_map_live_stage_to_terminal(test_db) -> None:
    item_id = 981
    insert_item(test_db, id=item_id, status="release")
    source_pin = int(
        test_db.execute(
            "SELECT workflow_version_id FROM items WHERE id=%s",
            (item_id,),
        ).fetchone()[0]
    )
    target = _publish_release_terminal_version(test_db)

    with pytest.raises(
        WorkflowRegistryError,
        match="non-terminal to terminal",
    ):
        migrate_item_workflow_pin(
            test_db,
            item_id=item_id,
            target_version=int(target["version"]),
        )

    row = test_db.execute(
        "SELECT status, workflow_version_id FROM items WHERE id=%s",
        (item_id,),
    ).fetchone()
    assert str(row[0]) == "release"
    assert int(row[1]) == source_pin


def test_migration_cannot_resurrect_terminal_stage(test_db) -> None:
    item_id = 982
    insert_item(test_db, id=item_id, status="done")
    source_pin = int(
        test_db.execute(
            "SELECT workflow_version_id FROM items WHERE id=%s",
            (item_id,),
        ).fetchone()[0]
    )
    target = publish_issue_completion_stage(test_db, stage_id="archived")

    with pytest.raises(
        WorkflowRegistryError,
        match="terminal to non-terminal",
    ):
        migrate_item_workflow_pin(
            test_db,
            item_id=item_id,
            target_version=int(target["version"]),
        )

    row = test_db.execute(
        "SELECT status, workflow_version_id FROM items WHERE id=%s",
        (item_id,),
    ).fetchone()
    assert str(row[0]) == "done"
    assert int(row[1]) == source_pin
