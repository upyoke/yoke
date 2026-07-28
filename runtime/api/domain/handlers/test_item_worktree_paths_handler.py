"""Registered full-lane reads and guarded path recording."""

from __future__ import annotations

from contextlib import nullcontext

from runtime.api.fixtures.backlog import insert_item
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain import db_helpers
from yoke_core.domain.handlers import (
    _register_item_worktrees,
    item_worktree_paths,
)
from yoke_core.domain.item_worktrees import (
    list_item_worktrees,
    record_item_worktree,
)


def _request(
    function_id: str,
    item_id: int,
    *,
    payload=None,
    preconditions=None,
) -> FunctionCallRequest:
    return FunctionCallRequest(
        function=function_id,
        actor=ActorContext(session_id="lane-path-test"),
        target=TargetRef(kind="item", item_id=item_id),
        payload=payload or {},
        preconditions=preconditions or {},
    )


def _seed_lanes(test_db, item_id: int) -> list[dict]:
    insert_item(
        test_db,
        id=item_id,
        workflow_id="blitz",
        status="implementing",
    )
    for branch, role in (
        (f"YOK-{item_id}", "worker"),
        ("blitz/docs", "worker"),
        ("blitz/integration", "integration"),
    ):
        record_item_worktree(
            test_db,
            item_id=item_id,
            branch=branch,
            path=None,
            lane_role=role,
        )
    test_db.commit()
    return list_item_worktrees(test_db, item_id, active_only=True)


def test_list_returns_every_active_worker_and_integration_lane(
    test_db,
    monkeypatch,
) -> None:
    expected = _seed_lanes(test_db, 981)
    monkeypatch.setattr(
        db_helpers, "connect", lambda: nullcontext(test_db),
    )

    outcome = item_worktree_paths.handle_list(
        _request("item_worktrees.list", 981),
    )

    assert outcome.primary_success is True
    assert [lane["id"] for lane in outcome.result_payload["worktrees"]] == [
        lane["id"] for lane in expected
    ]
    assert [
        lane["branch"] for lane in outcome.result_payload["worktrees"]
    ] == ["YOK-981", "blitz/docs", "blitz/integration"]


def test_path_record_requires_unchanged_active_lane_and_branch(
    test_db,
    monkeypatch,
) -> None:
    lanes = _seed_lanes(test_db, 982)
    worker = next(lane for lane in lanes if lane["branch"] == "blitz/docs")
    monkeypatch.setattr(
        db_helpers, "connect", lambda: nullcontext(test_db),
    )

    recorded = item_worktree_paths.handle_path_record(
        _request(
            "item_worktrees.path_record",
            982,
            payload={"path": "/tmp/blitz-docs"},
            preconditions={
                "worktree_id": worker["id"],
                "branch": "blitz/docs",
            },
        ),
    )
    stale = item_worktree_paths.handle_path_record(
        _request(
            "item_worktrees.path_record",
            982,
            payload={"path": "/tmp/blitz-docs-new"},
            preconditions={
                "worktree_id": worker["id"],
                "branch": "blitz/renamed",
            },
        ),
    )

    assert recorded.primary_success is True
    assert recorded.result_payload["worktree"]["path"] == "/tmp/blitz-docs"
    assert stale.primary_success is False
    assert stale.error is not None
    assert stale.error.code == "lane_precondition_stale"


def test_path_record_registration_requires_the_item_claim() -> None:
    entries = {}

    class Registry:
        def register(self, function_id, *args, **kwargs):
            entries[function_id] = kwargs

    _register_item_worktrees.register(Registry())

    assert entries["item_worktrees.list"]["claim_required_kind"] is None
    path = entries["item_worktrees.path_record"]
    assert path["claim_required_kind"] == "item"
    assert "active_lane_id_precondition" in path["guardrails"]
    assert "unchanged_branch_precondition" in path["guardrails"]
