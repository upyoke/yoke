from __future__ import annotations

import pytest

from yoke_core.domain.workflow_registry import (
    WorkflowRegistryError,
    resolve_current_workflow_pin,
)
from yoke_core.domain.workflow_runtime import load_item_workflow_runtime


def _create(test_db, item_type: str = "issue") -> int:
    workflow_id, version_id = resolve_current_workflow_pin(
        test_db,
        item_type,
    )
    item_id = 991
    test_db.execute(
        "INSERT INTO items "
        "(id, title, type, status, priority, created_at, updated_at, "
        "project_id, project_sequence, workflow_id, workflow_version_id) "
        "VALUES (%s, %s, %s, 'idea', 'medium', "
        "'2026-07-25T00:00:00Z', '2026-07-25T00:00:00Z', "
        "1, %s, %s, %s)",
        (
            item_id,
            f"Pinned {item_type}",
            item_type,
            item_id,
            workflow_id,
            version_id,
        ),
    )
    return item_id


def test_runtime_interprets_pinned_issue(test_db):
    runtime = load_item_workflow_runtime(test_db, _create(test_db))

    assert runtime.workflow_id == "issue"
    assert runtime.stage_ids[0] == "idea"
    assert runtime.accepts_stage("implementing") is True
    assert runtime.accepts_stage("planning") is False
    assert runtime.accepts_stage("failed") is True
    assert runtime.is_forward_transition("idea", "implementing") is True
    assert runtime.executor_for_stage("idea") == "refine"
    assert runtime.executor_for_stage("refined-idea") == "advance"
    assert runtime.executor_for_stage("implemented") == "usher"
    assert runtime.executor_for_stage("done") is None


def test_runtime_interprets_epic_executor_segments(test_db):
    runtime = load_item_workflow_runtime(test_db, _create(test_db, "epic"))

    assert runtime.executor_for_stage("idea") == "refine"
    assert runtime.executor_for_stage("refined-idea") == "shepherd"
    assert runtime.executor_for_stage("plan-drafted") == "refine"
    assert runtime.executor_for_stage("planned") == "conduct"


def test_runtime_exposes_definition_owned_gate_placement(test_db):
    runtime = load_item_workflow_runtime(test_db, _create(test_db))

    gates = runtime.gates_for_stage("implemented")

    assert [gate["id"] for gate in gates] == [
        "db_claim_prose",
        "db_mutation",
        "architecture_impact",
        "path_claim_boundary",
        "qa_verification",
    ]
    assert gates[1]["mode"] == "polish"


def test_runtime_refuses_missing_pin(test_db):
    item_id = _create(test_db)
    test_db.execute(
        "UPDATE items SET workflow_id = NULL, workflow_version_id = NULL "
        "WHERE id = %s",
        (item_id,),
    )

    with pytest.raises(
        WorkflowRegistryError,
        match="has no complete workflow-version pin",
    ):
        load_item_workflow_runtime(test_db, item_id)
