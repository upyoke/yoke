"""Epic-task lifecycle and workflow-runtime boundary tests."""

from __future__ import annotations

import pytest

from yoke_core.domain.task_lifecycle import (
    ALL_TASK_STATUSES,
    TERMINAL_FAILURE,
    TaskStatus,
    display_label,
    is_task_terminal_success,
    is_valid_task_status,
)
from yoke_core.domain.workflow_runtime import builtin_workflow_runtime


def test_task_status_collection_matches_the_enum():
    assert ALL_TASK_STATUSES == tuple(status.value for status in TaskStatus)


@pytest.mark.parametrize("status", ALL_TASK_STATUSES)
def test_every_task_status_validates(status):
    assert is_valid_task_status(status) is True


@pytest.mark.parametrize("status", ["idea", "cancelled", "bogus", ""])
def test_item_only_or_unknown_stages_are_not_task_statuses(status):
    assert is_valid_task_status(status) is False


def test_task_terminal_success_reads_the_parent_pin(monkeypatch):
    runtime = builtin_workflow_runtime("epic")
    monkeypatch.setattr(
        "yoke_core.domain.task_lifecycle.load_item_workflow_runtime",
        lambda conn, item_id: runtime,
    )
    for status in ALL_TASK_STATUSES:
        assert is_task_terminal_success(object(), 1, status) is (
            status in runtime.successful_task_stage_ids
        )


def test_task_terminal_failure_is_task_owned():
    assert TERMINAL_FAILURE == frozenset({"stopped", "failed"})


def test_display_label_is_generic():
    assert display_label("reviewing-implementation") == ("reviewing implementation")


@pytest.mark.parametrize("workflow_id", ["issue", "epic", "blitz", "dash", "task"])
def test_item_stage_order_is_owned_by_workflow_definitions(workflow_id):
    workflow = builtin_workflow_runtime(workflow_id)

    assert workflow.stage_ids
    assert workflow.terminal_stage_ids == frozenset({workflow.stage_ids[-1]})
    for before, after in zip(workflow.stage_ids, workflow.stage_ids[1:]):
        assert workflow.is_forward_transition(before, after)
