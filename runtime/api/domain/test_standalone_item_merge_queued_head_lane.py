"""A multi-lane item merges, proves and keys receipts by the queued-head lane.

An epic's composition lane can carry the queued pull request while its
integration lane holds an older head. The merge source is the lane at the
landing record's pull-request head; the integration rule applies only when no
lane is at that head.
"""

from __future__ import annotations

from pathlib import Path

from yoke_core.domain import standalone_item_merge_cli as merge_cli
from yoke_core.domain import standalone_item_merge_commit_bound as commit_bound
from yoke_core.domain import standalone_item_merge_qa as merge_qa
from yoke_core.domain.standalone_item_merge_lane import (
    lane_branch,
    lane_path,
    lane_resolution_error,
    merge_source_lane,
)
from runtime.api.domain.test_standalone_item_merge_lane import (
    _enter_release_wait_on_close_out,  # noqa: F401 - autouse fixture
    _item,
    _wire_cli,
)
from runtime.api.domain.test_standalone_item_merge_qa import _requirement

QUEUED_SHA = "c" * 40
INTEGRATION_SHA = "6" * 40
SIBLING_SHA = "9" * 40


def _epic(queued_head: str) -> dict:
    item = _item(
        [
            {
                "branch": "YOK-10-composition",
                "state": "active",
                "lane_role": "worker",
                "commit_sha": QUEUED_SHA,
                "path": "/composition",
            },
            {
                "branch": "YOK-10",
                "state": "active",
                "lane_role": "integration",
                "commit_sha": INTEGRATION_SHA,
                "path": "/integration",
            },
            {
                "branch": "YOK-10-sibling",
                "state": "active",
                "lane_role": "worker",
                "commit_sha": SIBLING_SHA,
                "path": "/sibling",
            },
        ]
    )
    item["merge_queue"] = {"pr_number": "2558", "head_sha": queued_head}
    return item


def test_queued_head_lane_wins_over_the_integration_lane() -> None:
    item = _epic(QUEUED_SHA)
    assert merge_source_lane(item)["branch"] == "YOK-10-composition"
    assert lane_branch(item, "YOK-10") == "YOK-10-composition"
    assert lane_path(item) == "/composition"
    assert lane_resolution_error(item) == ""


def test_integration_lane_remains_the_source_when_no_lane_is_at_the_head() -> None:
    for queued_head in ("", "e" * 40):
        item = _epic(queued_head)
        assert merge_source_lane(item)["branch"] == "YOK-10"


def test_preflight_verifies_the_queued_head(tmp_path: Path) -> None:
    item = _epic(QUEUED_SHA)
    item["qa_requirements"] = [_requirement(verdict="pass", sha=QUEUED_SHA)]
    commit_sha, error = merge_qa.preflight(
        item, public_ref="YOK-10", repo_root=tmp_path, branch="YOK-10-composition"
    )
    assert (commit_sha, error) == (QUEUED_SHA, "")


def test_merge_item_lands_and_keys_the_queued_head_lane(
    tmp_path: Path, monkeypatch
) -> None:
    merger = _wire_cli(monkeypatch, _epic(QUEUED_SHA), tmp_path)
    assert merge_cli.run(["YOK-10", "--skip-status"]) == 0
    assert merger.call_args.kwargs["branch"] == "YOK-10-composition"
    assert merger.call_args.kwargs["commit_sha"] == QUEUED_SHA


def test_parent_command_recovery_runs_in_the_queued_head_lane() -> None:
    requirement = _requirement(verdict="pass", sha=INTEGRATION_SHA)
    requirement["runner_id"] = "ci_run"
    item = _epic(QUEUED_SHA)
    item["qa_requirements"] = [requirement]
    _, issues, _ = merge_qa.evaluate(
        item, public_ref="YOK-10", repo_root=Path("/"), branch="YOK-10-composition"
    )
    ran = []

    error = commit_bound.recover_issues(
        item,
        issues,
        QUEUED_SHA,
        run_case=lambda requirement_id, lane, sha: ran.append(
            (requirement_id, lane["path"], lane["branch"], sha)
        ),
    )

    assert error == ""
    assert ran == [(77, "/composition", "YOK-10-composition", QUEUED_SHA)]


def test_case_rerun_selects_the_lane_and_pins_the_commit(monkeypatch) -> None:
    from yoke_core.domain import qa_case_execution

    calls = []
    monkeypatch.setattr(
        qa_case_execution,
        "execute_case",
        lambda requirement_id, **kwargs: calls.append((requirement_id, kwargs)),
    )
    lane = {"path": "/composition", "branch": "YOK-10-composition"}

    commit_bound.rerun_command_case(77, lane, QUEUED_SHA)

    assert calls == [
        (
            77,
            {
                "checkout_path": "/composition",
                "expected_branch": "YOK-10-composition",
                "expected_sha": QUEUED_SHA,
            },
        )
    ]


def test_rebinding_to_the_rebased_head_keeps_the_queued_lane(monkeypatch) -> None:
    rebased = "f" * 40
    monkeypatch.setattr(commit_bound.git, "head_of", lambda *_a: rebased)
    item = commit_bound.at_lane_head(
        _epic(QUEUED_SHA), repo_root=Path("/"), branch="YOK-10-composition"
    )
    lane = merge_source_lane(item)
    assert (lane["branch"], lane["commit_sha"]) == ("YOK-10-composition", rebased)
