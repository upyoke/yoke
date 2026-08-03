from __future__ import annotations

from copy import deepcopy
from dataclasses import replace

import pytest
from psycopg.rows import tuple_row

from yoke_core.domain.workflow_behavior import delivery_redirect_stage
from yoke_core.domain.workflow_registry import (
    WorkflowRegistryError,
    resolve_current_workflow_pin,
)
from yoke_core.domain.workflow_runtime import load_item_workflow_runtime


def _create(test_db, workflow_id: str = "issue") -> int:
    pinned_workflow_id, version_id = resolve_current_workflow_pin(
        test_db,
        workflow_id,
    )
    item_id = 991
    test_db.execute(
        "INSERT INTO items "
        "(id, title, status, priority, created_at, updated_at, "
        "project_id, project_sequence, workflow_id, workflow_version_id) "
        "VALUES (%s, %s, 'idea', 'medium', "
        "'2026-07-25T00:00:00Z', '2026-07-25T00:00:00Z', "
        "1, %s, %s, %s)",
        (
            item_id,
            f"Pinned {workflow_id}",
            item_id,
            pinned_workflow_id,
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


def test_runtime_normalizes_legacy_skill_bindings(test_db):
    runtime = load_item_workflow_runtime(test_db, _create(test_db, "dash"))
    definition = deepcopy(runtime.definition)
    definition["skill_bindings"] = [
        {
            "skill_id": binding["executor_id"],
            "from_stage_id": binding["from_stage_id"],
            "through_stage_id": binding["through_stage_id"],
        }
        for binding in definition.pop("executor_bindings")
    ]
    legacy_runtime = replace(runtime, definition=definition)

    assert legacy_runtime.executor_bindings == (
        {
            "executor_id": "dash",
            "from_stage_id": "idea",
            "through_stage_id": "done",
        },
    )
    assert legacy_runtime.executor_for_stage("implementing") == "dash"
    assert legacy_runtime.executor_has_started(
        "implementing", frozenset({"dash"})
    ) is True


def test_delivery_redirect_stage_comes_from_pinned_transition_graph(test_db):
    runtime = load_item_workflow_runtime(test_db, _create(test_db))
    definition = deepcopy(runtime.definition)
    for stage in definition["stages"]:
        if stage["id"] == "release":
            stage["id"] = "ship-ready"
            stage["label"] = "ship ready"
    for transition in definition["transitions"]:
        for field in ("from_stage_id", "to_stage_id"):
            if transition[field] == "release":
                transition[field] = "ship-ready"
    custom_runtime = replace(runtime, definition=definition)

    assert delivery_redirect_stage(custom_runtime) == "ship-ready"


def test_non_release_delivery_policy_has_no_redirect_stage(test_db):
    runtime = load_item_workflow_runtime(test_db, _create(test_db, "dash"))

    assert delivery_redirect_stage(runtime) is None


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


def test_runtime_refuses_unknown_item(test_db):
    with pytest.raises(
        WorkflowRegistryError,
        match="does not exist",
    ):
        load_item_workflow_runtime(test_db, 992)


def test_runtime_interprets_positional_postgres_rows(test_db):
    item_id = _create(test_db)
    original_row_factory = test_db.row_factory
    test_db.row_factory = tuple_row
    try:
        runtime = load_item_workflow_runtime(test_db, item_id)
    finally:
        test_db.row_factory = original_row_factory

    assert runtime.workflow_id == "issue"
    assert runtime.workflow_version_id > 0
