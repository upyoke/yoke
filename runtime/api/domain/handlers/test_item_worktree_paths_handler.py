"""Registered full-lane reads and guarded path recording."""

from __future__ import annotations

from contextlib import nullcontext

import pytest

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
        db_helpers,
        "connect",
        lambda: nullcontext(test_db),
    )

    outcome = item_worktree_paths.handle_list(
        _request("item_worktrees.list", 981),
    )

    assert outcome.primary_success is True
    assert [lane["id"] for lane in outcome.result_payload["worktrees"]] == [
        lane["id"] for lane in expected
    ]
    assert [lane["branch"] for lane in outcome.result_payload["worktrees"]] == [
        "YOK-981",
        "blitz/docs",
        "blitz/integration",
    ]


def test_path_record_requires_unchanged_active_lane_and_branch(
    test_db,
    monkeypatch,
) -> None:
    lanes = _seed_lanes(test_db, 982)
    worker = next(lane for lane in lanes if lane["branch"] == "blitz/docs")
    monkeypatch.setattr(
        db_helpers,
        "connect",
        lambda: nullcontext(test_db),
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


@pytest.mark.parametrize(
    "path",
    [
        "C:/git/hub/twoquarterrican/lean-java-trial/.worktrees/LJT-1",
        r"C:\git\hub\twoquarterrican\lean-java-trial\.worktrees\LJT-1",
        "c:/checkout with spaces/../lane",
        "C:/",
        "Z:\\",
        r"\\server\share",
        r"\\server\share\checkout",
        r"\\server/share\checkout",
        "/Users/example/project/.worktrees/lane",
        "/home/example/lane",
        "/tmp/lane",
        "/",
        "//",
        "///tmp/lane",
        "//server",
        "//server/share",
        "//?/C:/lane",
    ],
)
def test_client_path_round_trip_preserves_spelling(test_db, monkeypatch, path):
    from yoke_core.domain.handlers import item_worktrees as lane_handlers
    from yoke_core.domain.item_worktree_resolution import recorded_item_worktree_records

    lane = _seed_lanes(test_db, 983)[0]
    monkeypatch.setattr(db_helpers, "connect", lambda: nullcontext(test_db))
    recorded = item_worktree_paths.handle_path_record(
        _request(
            "item_worktrees.path_record",
            983,
            payload={"path": f"  {path}  "},
            preconditions={"worktree_id": lane["id"], "branch": lane["branch"]},
        )
    )
    assert recorded.primary_success, recorded.error
    assert recorded.result_payload["worktree"]["path"] == path
    listed = item_worktree_paths.handle_list(_request("item_worktrees.list", 983))
    assert listed.result_payload["worktrees"][0]["path"] == path
    fetched = lane_handlers.handle_get(
        _request("item_worktrees.get", 983, payload={"lane_role": "worker"})
    )
    assert fetched.result_payload["worktree"]["path"] == path
    resolved = recorded_item_worktree_records(test_db, 983, "/repo", ".worktrees")
    assert next(row for row in resolved if row["id"] == lane["id"])["path"] == path


@pytest.mark.parametrize(
    "path",
    [
        "",
        "   ",
        "lane",
        "./lane",
        "../lane",
        "C:project",
        "C:",
        r"\checkout",
        "\\",
        r"\\server",
        "\\\\server\\",
        r"\\?\C:\checkout",
        r"\\.\C:\checkout",
        r"\\?\UNC\server\share\lane",
        r"\??\C:\checkout",
        r"\\.\pipe\name",
    ],
)
def test_invalid_client_path_leaves_lanes_unchanged(test_db, monkeypatch, path):
    before = _seed_lanes(test_db, 984)
    lane = before[0]
    monkeypatch.setattr(db_helpers, "connect", lambda: nullcontext(test_db))
    refused = item_worktree_paths.handle_path_record(
        _request(
            "item_worktrees.path_record",
            984,
            payload={"path": path},
            preconditions={"worktree_id": lane["id"], "branch": lane["branch"]},
        )
    )
    assert refused.primary_success is False
    assert refused.error.code == (
        "payload_invalid" if path == "" else "path_record_refused"
    )
    assert "fully qualified client path" in refused.error.message
    if path:
        assert "Preserve an existing checkout" in refused.error.message
    assert list_item_worktrees(test_db, 984, active_only=True) == before


@pytest.mark.parametrize(
    "failure,code",
    [
        ("released", "lane_precondition_stale"),
        ("branch", "lane_precondition_stale"),
        ("foreign_lane", "lane_precondition_stale"),
        ("terminal", "item_inactive"),
        ("duplicate", "path_record_refused"),
    ],
)
def test_client_path_registration_preserves_safeguards(
    test_db, monkeypatch, failure, code
):
    from yoke_core.domain.item_worktrees import release_item_worktrees

    lane = _seed_lanes(test_db, 985)[0]
    foreign = _seed_lanes(test_db, 986)[0]
    path = "C:/checkout/lane"
    lane_id, branch = lane["id"], lane["branch"]
    if failure == "released":
        release_item_worktrees(test_db, item_id=985)
    elif failure == "branch":
        branch = "changed-branch"
    elif failure == "foreign_lane":
        lane_id = foreign["id"]
    elif failure == "terminal":
        test_db.execute("UPDATE items SET status='done' WHERE id=%s", (985,))
    else:
        test_db.execute(
            "UPDATE item_worktrees SET path=%s WHERE id=%s", (path, foreign["id"])
        )
    test_db.commit()
    before = list_item_worktrees(test_db, 985)
    foreign_before = list_item_worktrees(test_db, 986)
    monkeypatch.setattr(db_helpers, "connect", lambda: nullcontext(test_db))
    refused = item_worktree_paths.handle_path_record(
        _request(
            "item_worktrees.path_record",
            985,
            payload={"path": path},
            preconditions={"worktree_id": lane_id, "branch": branch},
        )
    )
    assert refused.primary_success is False
    assert refused.error.code == code
    assert list_item_worktrees(test_db, 985) == before
    assert list_item_worktrees(test_db, 986) == foreign_before
