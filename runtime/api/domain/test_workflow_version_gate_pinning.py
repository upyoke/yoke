"""Behavioral proof that gate placement stays pinned across publication."""

from __future__ import annotations

from copy import deepcopy

from runtime.api.fixtures.backlog_inserts import insert_item
from yoke_core.domain.workflow_registry import (
    get_workflow_version,
    list_current_workflows,
    publish_workflow_version,
)
from yoke_core.domain.workflow_runtime import load_item_workflow_runtime


def _current_issue(conn) -> dict:
    return next(row for row in list_current_workflows(conn) if row["id"] == "issue")


def test_new_gate_placement_does_not_change_existing_item_runtime(test_db) -> None:
    current = _current_issue(test_db)
    insert_item(test_db, id=2921, title="Pinned gates")
    before = load_item_workflow_runtime(test_db, 2921)
    before_gates = before.gates_for_stage("implemented")
    assert "qa_verification" in {gate["id"] for gate in before_gates}

    version = get_workflow_version(
        test_db,
        workflow_id="issue",
        version=int(current["current_version"]),
    )
    changed = deepcopy(version["definition"])
    implemented = next(
        stage for stage in changed["stages"] if stage["id"] == "implemented"
    )
    implemented["gates"] = [
        gate for gate in implemented["gates"] if gate["id"] != "qa_verification"
    ]
    publish_workflow_version(
        test_db,
        workflow_id="issue",
        definition=changed,
    )
    insert_item(test_db, id=2922, title="Current gates")

    pinned = load_item_workflow_runtime(test_db, 2921)
    current_runtime = load_item_workflow_runtime(test_db, 2922)
    assert pinned.version == before.version
    assert pinned.gates_for_stage("implemented") == before_gates
    assert "qa_verification" not in {
        gate["id"] for gate in current_runtime.gates_for_stage("implemented")
    }
