# ruff: noqa: F811
"""Authoring and evaluation for status:<stage-id> dependency satisfactions."""

from __future__ import annotations

from typing import Any

import pytest

from runtime.api.domain.test_dependency_deployed_satisfaction import (
    WORKFLOW,
    _insert_item,
    dependency_conn,  # noqa: F401
)
from yoke_core.domain.dependencies import Satisfaction
from yoke_core.domain.dependency_explanation import satisfaction_description
from yoke_core.domain.dependency_planning import evaluate_item_gate
from yoke_core.domain.dependency_satisfaction import evaluate_satisfaction
from yoke_core.domain.dependency_types import SATISFACTION_GRAMMAR, status_stage_id
from yoke_core.domain.item_dependency import cmd_dependency_add
from yoke_core.domain.workflow_registry import resolve_current_workflow_pin
from yoke_core.domain.workflow_runtime import WorkflowRuntime, builtin_workflow_runtime


def _pin_item(conn: Any, item_id: int, workflow_id: str, *, status: str) -> None:
    workflow_id, version_id = resolve_current_workflow_pin(conn, workflow_id)
    conn.execute(
        "UPDATE items SET workflow_id=%s, workflow_version_id=%s, status=%s WHERE id=%s",
        (workflow_id, version_id, status, item_id),
    )


def test_grammar_and_parser_admit_any_status_stage() -> None:
    assert "status:<stage-id>" in SATISFACTION_GRAMMAR
    assert status_stage_id("status:reviewing-implementation") == (
        "reviewing-implementation"
    )
    value = Satisfaction.from_db("status:reviewing-implementation")
    assert value.value == "status:reviewing-implementation"
    assert Satisfaction.from_db("status:done") == Satisfaction.STATUS_DONE
    assert Satisfaction.from_db("status:implemented") == Satisfaction.STATUS_IMPLEMENTED


def test_authoring_accepts_a_stage_from_the_blocker_pin(
    dependency_conn: Any,
) -> None:
    _insert_item(dependency_conn, 1)
    _insert_item(dependency_conn, 2)
    assert (
        cmd_dependency_add(
            dependency_conn,
            "YOK-1",
            "YOK-2",
            "operator",
            satisfaction="status:reviewing-implementation",
        )
        == "OK"
    )
    stored = dependency_conn.execute(
        "SELECT satisfaction FROM item_dependencies"
    ).fetchone()[0]
    assert stored == "status:reviewing-implementation"


def test_authoring_refuses_unknown_stage_and_lists_available(
    dependency_conn: Any,
) -> None:
    _insert_item(dependency_conn, 1)
    _insert_item(dependency_conn, 2)
    with pytest.raises(ValueError, match="unknown_status_stage") as raised:
        cmd_dependency_add(
            dependency_conn,
            "YOK-1",
            "YOK-2",
            "operator",
            satisfaction="status:not-a-stage",
        )
    message = str(raised.value)
    assert "available stages:" in message
    assert "reviewing-implementation" in message
    assert "done" in message


def test_legacy_status_values_stay_authorable_without_that_stage(
    dependency_conn: Any,
) -> None:
    _insert_item(dependency_conn, 1)
    _insert_item(dependency_conn, 2)
    _pin_item(dependency_conn, 2, "dash", status="implementing")
    dash = builtin_workflow_runtime("dash")
    assert "implemented" not in dash.stage_ids
    assert (
        cmd_dependency_add(
            dependency_conn,
            "YOK-1",
            "YOK-2",
            "operator",
            satisfaction="status:implemented",
        )
        == "OK"
    )
    assert (
        cmd_dependency_add(
            dependency_conn,
            "YOK-1",
            "YOK-2",
            "operator",
            gate_point="closure",
            satisfaction="status:done",
        )
        == "OK"
    )


def test_evaluation_uses_the_general_milestone_helper() -> None:
    before = evaluate_satisfaction(
        "status:reviewing-implementation",
        "implementing",
        workflow=WORKFLOW,
    )
    at_stage = evaluate_satisfaction(
        "status:reviewing-implementation",
        "reviewing-implementation",
        workflow=WORKFLOW,
    )
    later = evaluate_satisfaction(
        "status:reviewing-implementation",
        "implemented",
        workflow=WORKFLOW,
    )
    assert before.satisfied is False
    assert "must reach reviewing-implementation" in before.reason
    assert at_stage.satisfied is True
    assert later.satisfied is True
    done = evaluate_satisfaction("status:done", "done", workflow=WORKFLOW)
    implemented = evaluate_satisfaction(
        "status:implemented", "release", workflow=WORKFLOW
    )
    assert done.satisfied is True
    assert implemented.satisfied is True
    assert done.reason == "Blocking item has reached done."
    assert implemented.reason == "Blocking item has reached implemented or later."


def test_stored_edge_still_evaluates_when_the_pin_drops_the_stage() -> None:
    stages = [
        stage
        for stage in WORKFLOW.definition["stages"]
        if str(stage["id"]) != "reviewing-implementation"
    ]
    superseded = WorkflowRuntime(
        workflow_id=WORKFLOW.workflow_id,
        workflow_version_id=WORKFLOW.workflow_version_id,
        version=WORKFLOW.version,
        definition_digest=WORKFLOW.definition_digest,
        definition={**dict(WORKFLOW.definition), "stages": stages},
    )
    open_item = evaluate_satisfaction(
        "status:reviewing-implementation",
        "implementing",
        workflow=superseded,
    )
    terminal = evaluate_satisfaction(
        "status:reviewing-implementation",
        "done",
        workflow=superseded,
    )
    assert open_item.satisfied is False
    assert terminal.satisfied is True


def test_gate_reader_honours_a_middle_stage_wait(
    dependency_conn: Any,
) -> None:
    _insert_item(dependency_conn, 1)
    _insert_item(dependency_conn, 2, status="implementing")
    cmd_dependency_add(
        dependency_conn,
        "YOK-1",
        "YOK-2",
        "operator",
        satisfaction="status:reviewing-implementation",
    )
    blocked = evaluate_item_gate(dependency_conn, "YOK-1", "activation")
    assert blocked.is_blocked is True
    assert "reviewing-implementation" in blocked.unsatisfied_blockers[0].reason
    dependency_conn.execute(
        "UPDATE items SET status='reviewing-implementation' WHERE id=2"
    )
    cleared = evaluate_item_gate(dependency_conn, "YOK-1", "activation")
    assert cleared.is_blocked is False


def test_explanations_name_an_arbitrary_stage() -> None:
    assert satisfaction_description("status:done") == "status reaches done"
    assert satisfaction_description("status:implemented") == (
        "status reaches implemented"
    )
    assert satisfaction_description("status:reviewing-implementation") == (
        "status reaches reviewing-implementation"
    )
