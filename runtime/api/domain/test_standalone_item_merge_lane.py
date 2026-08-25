"""Standalone merge source follows the active item worktree lane topology."""

from __future__ import annotations

from pathlib import Path
from unittest import mock

from yoke_core.domain import standalone_item_merge as merge_domain
from yoke_core.domain import standalone_item_merge_cli as merge_cli
from yoke_core.domain import standalone_item_merge_verify as verify
from yoke_core.domain import standalone_item_merge_qa as merge_qa
from yoke_core.domain import standalone_item_merge_recovery as recovery
from yoke_core.domain.standalone_item_merge_lane import (
    lane_branch,
    lane_path,
    lane_resolution_error,
    merge_source_lane,
)
from yoke_core.domain.standalone_item_merge_receipt import MergeReceipt
from yoke_core.domain.standalone_item_merge_recovery import with_recorded_head


RELEASED_SHA = "a" * 40
ACTIVE_SHA = "b" * 40
OTHER_SHA = "c" * 40


def _item(worktrees: list[dict]) -> dict:
    return {
        "id": 10,
        "public_ref": "YOK-10",
        "status": "reviewing-implementation",
        "project": {"slug": "yoke"},
        "workflow": {"id": "dash"},
        "worktrees": worktrees,
        "qa_plan_attachments": [],
        "qa_requirements": [],
    }


def _stale_and_live() -> list[dict]:
    return [
        {
            "branch": "YOK-10",
            "state": "released",
            "commit_sha": RELEASED_SHA,
            "path": "/old",
        },
        {
            "branch": "YOK-10",
            "state": "active",
            "commit_sha": ACTIVE_SHA,
            "path": "/live",
        },
    ]


def _worker_and_integration() -> list[dict]:
    return [
        {
            "branch": "YOK-10-worker",
            "state": "active",
            "lane_role": "worker",
            "commit_sha": OTHER_SHA,
            "path": "/worker",
        },
        {
            "branch": "YOK-10-integration",
            "state": "active",
            "lane_role": "integration",
            "commit_sha": ACTIVE_SHA,
            "path": "/integration",
        },
    ]


def _wire_cli(monkeypatch, item: dict, tmp_path: Path) -> mock.Mock:
    monkeypatch.setattr(merge_cli, "_resolve_item", lambda *_a: (item, ""))
    monkeypatch.setattr(merge_cli, "_session_holds_claim", lambda *_a: "")
    monkeypatch.setattr(merge_cli.landed, "landed_lane", lambda **_kw: None)
    monkeypatch.setattr(
        merge_cli, "_resolve_checkout", lambda *_a: (tmp_path, "main"),
    )
    outcome = mock.Mock(
        ok=True, already_merged=False, commit_sha=ACTIVE_SHA,
        merge_sha=OTHER_SHA, touched_files=("file.py",), pushed=True,
        warnings=(),
    )
    merger = mock.Mock(return_value=outcome)
    monkeypatch.setattr(verify, "route_standalone_landing", merger)
    monkeypatch.setattr(merge_domain, "sync_item_to_github", lambda _item_id: None)
    return merger


def test_released_lane_on_main_does_not_become_the_merge_source() -> None:
    item = _item(_stale_and_live())
    assert merge_source_lane(item)["commit_sha"] == ACTIVE_SHA
    assert lane_branch(item, "YOK-10") == "YOK-10"
    assert lane_resolution_error(item) == ""


def test_preflight_uses_the_active_head_not_a_released_record(
    tmp_path: Path,
) -> None:
    commit_sha, error = merge_qa.preflight(
        _item(_stale_and_live()),
        item_ref="YOK-10",
        repo_root=tmp_path,
        branch="YOK-10",
    )
    assert error == ""
    assert commit_sha == ACTIVE_SHA


def test_merge_item_lands_the_active_lane_when_a_released_record_is_stale(
    tmp_path: Path, monkeypatch,
) -> None:
    merger = _wire_cli(monkeypatch, _item(_stale_and_live()), tmp_path)
    assert merge_cli.run(["YOK-10", "--skip-status"]) == 0
    assert merger.call_args.kwargs["commit_sha"] == ACTIVE_SHA
    assert merger.call_args.kwargs["branch"] == "YOK-10"


def test_already_merged_cannot_be_derived_from_a_released_record(
    tmp_path: Path,
) -> None:
    commit_sha, error = merge_qa.preflight(
        _item([{
            "branch": "YOK-10",
            "state": "released",
            "commit_sha": RELEASED_SHA,
        }]),
        item_ref="YOK-10",
        repo_root=tmp_path,
        branch="YOK-10",
    )
    assert commit_sha == ""
    assert "no active worktree lane" in error


def test_zero_active_lanes_are_a_named_error() -> None:
    error = lane_resolution_error(_item([]))
    assert error.startswith("no active worktree lane")
    assert merge_source_lane(_item([])) is None


def test_merge_item_refuses_zero_active_lanes(
    tmp_path: Path, monkeypatch, capsys,
) -> None:
    merger = _wire_cli(monkeypatch, _item([]), tmp_path)
    monkeypatch.setattr(recovery, "branch_needs_receipt", lambda *_a: False)
    assert merge_cli.run(["YOK-10", "--skip-status"]) == 1
    assert "no active worktree lane" in capsys.readouterr().err
    merger.assert_not_called()


def test_worker_and_integration_lanes_choose_the_integration_source(
    tmp_path: Path,
    monkeypatch,
) -> None:
    item = _item(_worker_and_integration())
    assert merge_source_lane(item)["branch"] == "YOK-10-integration"
    assert lane_branch(item, "YOK-10") == "YOK-10-integration"
    assert lane_path(item) == "/integration"
    assert lane_resolution_error(item) == ""

    merger = _wire_cli(monkeypatch, item, tmp_path)
    assert merge_cli.run(["YOK-10", "--skip-status"]) == 0
    assert merger.call_args.kwargs["branch"] == "YOK-10-integration"
    assert merger.call_args.kwargs["commit_sha"] == ACTIVE_SHA


def test_single_worker_lane_remains_the_merge_source() -> None:
    worker = _worker_and_integration()[0]
    item = _item([worker])
    assert merge_source_lane(item) is worker
    assert lane_resolution_error(item) == ""


def test_multiple_workers_without_integration_are_a_named_error(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    item = _item(
        [
            {
                "branch": "YOK-10-worker-a",
                "state": "active",
                "lane_role": "worker",
                "commit_sha": ACTIVE_SHA,
            },
            {
                "branch": "YOK-10-worker-b",
                "state": "active",
                "lane_role": "worker",
                "commit_sha": OTHER_SHA,
            },
        ]
    )
    error = lane_resolution_error(item)
    assert error.startswith("multiple active worktree lanes")
    assert "YOK-10-worker-a (worker)" in error
    assert "YOK-10-worker-b (worker)" in error
    assert merge_source_lane(item) is None

    merger = _wire_cli(monkeypatch, item, tmp_path)
    assert merge_cli.run(["YOK-10", "--skip-status"]) == 1
    assert "multiple active worktree lanes" in capsys.readouterr().err
    merger.assert_not_called()


def test_receipt_recovery_presents_one_active_lane() -> None:
    item = with_recorded_head(
        _item([{
            "branch": "YOK-10",
            "state": "released",
            "commit_sha": RELEASED_SHA,
        }]),
        MergeReceipt(
            branch="YOK-10",
            target="main",
            commit_sha=ACTIVE_SHA,
        ),
    )
    assert lane_resolution_error(item) == ""
    assert merge_source_lane(item)["commit_sha"] == ACTIVE_SHA
    assert merge_source_lane(item)["state"] == "active"
