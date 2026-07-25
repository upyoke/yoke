"""Frontier routing from immutable workflow executor bindings."""

from __future__ import annotations

import pytest

from yoke_core.domain.frontier_classify import classify_next_action
from yoke_core.domain.frontier_types import AdapterCategory
from yoke_core.domain.workflow_runtime import builtin_workflow_runtime


@pytest.mark.parametrize(
    "workflow_id,stage_id,expected",
    [
        ("issue", "idea", AdapterCategory.REFINE),
        ("issue", "refined-idea", AdapterCategory.ADVANCE),
        ("issue", "implementing", AdapterCategory.ADVANCE),
        ("issue", "reviewed-implementation", AdapterCategory.POLISH),
        ("issue", "implemented", AdapterCategory.USHER),
        ("epic", "idea", AdapterCategory.REFINE),
        ("epic", "refined-idea", AdapterCategory.SHEPHERD),
        ("epic", "plan-drafted", AdapterCategory.REFINE),
        ("epic", "planned", AdapterCategory.CONDUCT),
        ("epic", "reviewed-implementation", AdapterCategory.POLISH),
        ("epic", "implemented", AdapterCategory.USHER),
        ("blitz", "refined-idea", AdapterCategory.BLITZ),
        ("dash", "idea", AdapterCategory.DASH),
    ],
)
def test_definition_executor_selects_frontier_adapter(
    workflow_id,
    stage_id,
    expected,
):
    workflow = builtin_workflow_runtime(workflow_id)
    assert classify_next_action(workflow, stage_id) is expected


@pytest.mark.parametrize("stage_id", ["done", "cancelled", "stopped"])
def test_terminal_and_stopped_items_skip(stage_id):
    workflow = builtin_workflow_runtime("issue")
    assert classify_next_action(workflow, stage_id) is AdapterCategory.SKIP


@pytest.mark.parametrize("stage_id", ["blocked", "failed"])
def test_wait_states_are_engine_owned(stage_id):
    workflow = builtin_workflow_runtime("issue")
    assert classify_next_action(workflow, stage_id) is AdapterCategory.WAIT


def test_unknown_stage_fails_against_the_pin():
    workflow = builtin_workflow_runtime("issue")
    with pytest.raises(ValueError, match="Unknown stage"):
        classify_next_action(workflow, "planning")


def test_item_claim_probe_comes_from_next_stage_gate_and_policy():
    issue = builtin_workflow_runtime("issue")
    epic = builtin_workflow_runtime("epic")

    assert issue.requires_item_path_claim_probe("refined-idea") is True
    assert epic.requires_item_path_claim_probe("planned") is False


def test_executor_active_state_comes_from_binding_boundaries():
    implementation_executors = frozenset({"advance", "conduct"})
    issue = builtin_workflow_runtime("issue")

    assert issue.executor_has_started(
        "refined-idea", implementation_executors,
    ) is False
    assert issue.executor_has_started(
        "implementing", implementation_executors,
    ) is True
    assert issue.executor_has_started(
        "reviewing-implementation", implementation_executors,
    ) is True
    assert issue.executor_has_started(
        "reviewed-implementation", implementation_executors,
    ) is False


@pytest.mark.parametrize(
    "workflow_id,before,active",
    [
        ("issue", "refined-idea", "implementing"),
        ("epic", "planned", "implementing"),
        ("blitz", "refined-idea", "implementing"),
        ("dash", "idea", "implementing"),
    ],
)
def test_implementation_boundary_comes_from_registered_executor_bindings(
    workflow_id,
    before,
    active,
):
    workflow = builtin_workflow_runtime(workflow_id)

    assert workflow.is_before_implementation(before) is True
    assert workflow.implementation_has_started(before) is False
    assert workflow.is_before_implementation(active) is False
    assert workflow.implementation_has_started(active) is True


def test_reached_stage_uses_the_pinned_order_and_rejects_missing_stages():
    workflow = builtin_workflow_runtime("issue")

    assert workflow.has_reached_stage("release", "implemented") is True
    assert workflow.has_reached_stage("refined-idea", "implemented") is False
    assert workflow.has_reached_stage("planning", "implemented") is False
