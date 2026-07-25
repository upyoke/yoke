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
