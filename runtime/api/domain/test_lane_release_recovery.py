"""Evidence-only lane recovery follows the item's pinned workflow."""

from __future__ import annotations

from contextlib import nullcontext

from runtime.api.fixtures.backlog import insert_item
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain import db_helpers
from yoke_core.domain.handlers import item_worktrees as handlers
from yoke_core.domain.item_worktrees import (
    list_item_worktrees,
    record_item_worktree,
)
from yoke_core.domain.workflow_behavior import (
    LANE_IMPLEMENTATION,
    lane_release_recovery_statuses,
)
from yoke_core.domain.workflow_runtime import builtin_workflow_runtime


def _request(*, item_id: int, payload: dict) -> FunctionCallRequest:
    return FunctionCallRequest(
        function="item_worktrees.release",
        actor=ActorContext(session_id="lane-release-recovery-test"),
        target=TargetRef(kind="item", item_id=item_id),
        payload=payload,
    )


def _use_test_connection(monkeypatch, test_db) -> None:
    monkeypatch.setattr(db_helpers, "connect", lambda: nullcontext(test_db))


def test_issue_recovery_statuses_are_implementation_handoffs() -> None:
    statuses = lane_release_recovery_statuses(builtin_workflow_runtime("issue"))
    assert "implemented" in statuses
    assert "reviewed-implementation" in statuses
    assert "release" not in statuses
    assert "implementing" not in statuses


def test_dash_recovery_status_is_the_verification_close() -> None:
    statuses = lane_release_recovery_statuses(builtin_workflow_runtime("dash"))
    assert statuses == frozenset({"reviewing-implementation"})


def test_release_accepts_dash_reviewing_implementation(
    test_db,
    monkeypatch,
) -> None:
    insert_item(
        test_db,
        id=948,
        workflow_id="dash",
        status="reviewing-implementation",
    )
    lane = record_item_worktree(
        test_db,
        item_id=948,
        branch="YOK-948",
        path="/tmp/yoke-948",
        lane_role=LANE_IMPLEMENTATION,
    )
    _use_test_connection(monkeypatch, test_db)

    outcome = handlers.handle_release(
        _request(
            item_id=948,
            payload={
                "all_active": True,
                "reason": "evidence-only-recovery",
                "clean_lane_attestation": {
                    "worktree_id": lane["id"],
                    "branch": lane["branch"],
                    "path": lane["path"],
                    "observed_clean": True,
                },
            },
        )
    )

    assert outcome.primary_success is True, outcome.error
    assert list_item_worktrees(test_db, 948, active_only=True) == []


def test_release_refuses_dash_implementing_and_names_accepted_stages(
    test_db,
    monkeypatch,
) -> None:
    insert_item(test_db, id=949, workflow_id="dash", status="implementing")
    record_item_worktree(
        test_db,
        item_id=949,
        branch="YOK-949",
        path="/tmp/yoke-949",
        lane_role=LANE_IMPLEMENTATION,
    )
    _use_test_connection(monkeypatch, test_db)

    outcome = handlers.handle_release(
        _request(
            item_id=949,
            payload={
                "all_active": True,
                "reason": "evidence-only-recovery",
            },
        )
    )

    assert outcome.primary_success is False
    assert outcome.error is not None
    assert outcome.error.code == "recovery_status_invalid"
    assert "reviewing-implementation" in outcome.error.message
    assert "implementing" in outcome.error.message
    assert list_item_worktrees(test_db, 949, active_only=True)
