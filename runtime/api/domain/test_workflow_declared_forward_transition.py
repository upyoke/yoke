"""Forward status moves must be edges the pinned definition declares."""

from __future__ import annotations

import pytest

from runtime.api.fixtures.backlog import insert_item
from yoke_core.domain import workflow_declared_transitions as declared
from yoke_core.domain.status_claim_bypass_context import (
    STATUS_SOURCE_ENV_VAR,
    status_bypass_override,
)
from yoke_core.domain.workflow_runtime import builtin_workflow_runtime
from yoke_core.domain.workflow_status_transition_preflight import (
    prepare_status_transition,
)


def _refusal(workflow_id: str, before: str, after: str) -> str:
    return declared.undeclared_forward_transition(
        builtin_workflow_runtime(workflow_id),
        from_stage_id=before,
        to_stage_id=after,
    )


def test_close_out_straight_from_implementation_is_refused() -> None:
    refusal = _refusal("dash", "implementing", "done")

    assert "declares no transition" in refusal
    assert "reviewing-implementation" in refusal


def test_the_declared_next_stage_is_allowed() -> None:
    assert _refusal("dash", "implementing", "reviewing-implementation") == ""


@pytest.mark.parametrize(
    ("workflow_id", "before", "after"),
    [
        # Rework: back to implementation after review found something.
        ("dash", "reviewing-implementation", "implementing"),
        # Reopening: an item leaves and re-enters through an exceptional stage.
        ("dash", "implementing", "cancelled"),
        ("dash", "blocked", "implementing"),
        # A definition that declares the jump owns it.
        ("task", "implementing", "done"),
    ],
)
def test_supported_paths_stay_open(
    workflow_id: str,
    before: str,
    after: str,
) -> None:
    assert _refusal(workflow_id, before, after) == ""


def test_a_skipped_middle_stage_is_refused_late_in_the_lifecycle() -> None:
    assert _refusal("issue", "implemented", "release") == ""
    assert "declares no transition" in _refusal("issue", "implemented", "done")


@pytest.mark.parametrize(
    ("workflow_id", "expected"),
    [
        ("dash", "reviewing-implementation"),
        ("blitz", "reviewing-implementation"),
        ("issue", "reviewing-implementation"),
        ("epic", "reviewing-implementation"),
        # The floor workflow delivers from implementation with no review.
        ("task", None),
    ],
)
def test_review_stage_is_read_from_the_definition(
    workflow_id: str,
    expected: str | None,
) -> None:
    workflow = builtin_workflow_runtime(workflow_id)

    assert declared.implementation_review_stage_id(workflow) == expected


def test_review_is_unreached_until_the_item_arrives_there() -> None:
    workflow = builtin_workflow_runtime("dash")

    assert declared.unreached_review_stage(workflow, "implementing") == (
        "reviewing-implementation"
    )
    assert declared.unreached_review_stage(workflow, "reviewing-implementation") == ""
    assert declared.unreached_review_stage(workflow, "done") == ""


def _preflight(conn, item_id: int, target_status: str):
    return prepare_status_transition(
        conn,
        item_id=item_id,
        target_status=target_status,
        originator_actor_id=None,
        session_id="declared-edge-preflight",
    )


def test_preflight_refuses_the_undeclared_jump_before_materializing(
    test_db,
) -> None:
    insert_item(test_db, id=8801, workflow_id="dash", status="implementing")

    failure = _preflight(test_db, 8801, "done").failure

    assert failure is not None
    assert failure["error_code"] == "VALIDATION_ERROR"
    assert "declares no transition" in failure["error"]


def test_preflight_admits_the_declared_next_stage(test_db) -> None:
    insert_item(test_db, id=8802, workflow_id="dash", status="implementing")

    assert _preflight(test_db, 8802, "reviewing-implementation").failure is None


def test_a_write_that_names_its_source_keeps_its_reconciliation_authority(
    test_db,
    monkeypatch,
) -> None:
    insert_item(test_db, id=8803, workflow_id="dash", status="implementing")

    with status_bypass_override(
        claim_bypass="repair-status:recorded status was wrong",
        status_source="repair-status:recorded status was wrong",
        task_done_verified=True,
    ):
        assert _preflight(test_db, 8803, "done").failure is None

    monkeypatch.setenv(STATUS_SOURCE_ENV_VAR, "done-transition")
    insert_item(test_db, id=8804, workflow_id="dash", status="implementing")

    assert _preflight(test_db, 8804, "done").failure is None
