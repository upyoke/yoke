"""Commit-bound merge preflight refusals recover, then land."""

from __future__ import annotations

from pathlib import Path
from unittest import mock

import pytest

from yoke_core.domain import standalone_item_merge as merge_domain
from yoke_core.domain import standalone_item_merge_landed as landed
from yoke_core.domain import standalone_item_merge_cli as merge_cli
from yoke_core.domain import standalone_item_merge_verify as verify
from yoke_core.domain import standalone_item_merge_commit_bound as commit_bound
from yoke_core.domain import standalone_item_merge_recovery as merge_recovery
from runtime.api.domain.test_standalone_item_merge_qa import (
    EARLIER_SHA,
    MERGING_SHA,
    _item,
    _requirement,
)
from runtime.api.domain.merge_route_gate_stubs import admit_route_gates


@pytest.fixture(autouse=True)
def _enter_release_wait_on_close_out(monkeypatch):
    monkeypatch.setattr(
        merge_cli.close_out,
        "transition_to_done",
        lambda **kwargs: (
            (tuple(kwargs.get("stages") or ("release",)) or ("release",))[-1],
            "",
        ),
    )


def _run_merge(
    tmp_path: Path, monkeypatch, item, *, rerecord, run_case=None, resolve=None
):
    monkeypatch.setattr(merge_cli, "_resolve_item", resolve or (lambda *a: (item, "")))
    monkeypatch.setattr(merge_cli, "_session_holds_claim", lambda *a: "")
    monkeypatch.setattr(landed, "landed_lane", lambda **_kw: None)
    monkeypatch.setattr(merge_recovery, "branch_needs_receipt", lambda *a: False)
    monkeypatch.setattr(merge_cli, "_resolve_checkout", lambda *a: (tmp_path, "main"))
    admit_route_gates(monkeypatch)
    monkeypatch.setattr(
        commit_bound,
        "rerecord_hand_run",
        rerecord,
    )
    if run_case is not None:
        monkeypatch.setattr(commit_bound, "rerun_command_case", run_case)
    outcome = merge_domain.StandaloneMergeOutcome(
        exit_code=0,
        ok=True,
        already_merged=False,
        commit_sha=MERGING_SHA,
        merge_sha="c" * 40,
        touched_files=("file.py",),
        pushed=True,
        warnings=(),
    )
    merger = mock.Mock(return_value=outcome)
    monkeypatch.setattr(verify, "route_standalone_landing", merger)
    monkeypatch.setattr(merge_domain, "sync_item_to_github", lambda _item_id: None)
    return merge_cli.run(["YOK-10", "--skip-status"]), merger


def test_methodless_hand_acceptance_is_re_recorded_then_lands(
    tmp_path: Path,
    monkeypatch,
):
    item = _item(_requirement(verdict="pass", sha=""))
    recorded = []

    def rerecord(requirement, commit_sha):
        recorded.append((requirement["id"], commit_sha))
        requirement["recorded_head_sha"] = commit_sha
        requirement["verdict"] = "pass"
        requirement["completed_at"] = "2026-01-01T00:00:00Z"
        requirement["run_id"] = 88

    code, merger = _run_merge(tmp_path, monkeypatch, item, rerecord=rerecord)
    assert code == 0
    assert recorded == [(77, MERGING_SHA)]
    merger.assert_called_once()
    assert merger.call_args.kwargs["commit_sha"] == MERGING_SHA


def test_stale_sha_is_re_recorded_then_lands(tmp_path: Path, monkeypatch):
    item = _item(_requirement(verdict="pass", sha=EARLIER_SHA))
    recorded = []

    def rerecord(requirement, commit_sha):
        recorded.append(commit_sha)
        requirement["recorded_head_sha"] = commit_sha
        requirement["verdict"] = "pass"
        requirement["completed_at"] = "2026-01-01T00:00:00Z"
        requirement["run_id"] = 88

    code, merger = _run_merge(tmp_path, monkeypatch, item, rerecord=rerecord)
    assert code == 0
    assert recorded == [MERGING_SHA]
    merger.assert_called_once()


REBASED_SHA = "d" * 40


def _command_case_merge(tmp_path, monkeypatch, *, verdict="pass"):
    """The gate rebases the lane, tests the new head, and records that run."""
    requirement = _requirement(verdict="pass", sha="")
    requirement["method_id"] = "command-ci"
    requirement["runner_id"] = "ci_run"
    item = _item(requirement)
    ran = []
    lane_head = [MERGING_SHA]

    def run_case(requirement_id, _lane, _commit_sha):
        ran.append(requirement_id)
        lane_head[0] = REBASED_SHA
        requirement.update(run_id=89, verdict=verdict, recorded_head_sha=REBASED_SHA)
        if verdict != "pass":
            requirement["case_outcome"] = "failed"

    def rerecord(_requirement, _commit_sha):
        raise AssertionError("hand re-record is not the command-case path")

    monkeypatch.setattr(commit_bound.git, "head_of", lambda *_a: lane_head[0])
    code, merger = _run_merge(
        tmp_path, monkeypatch, item, rerecord=rerecord, run_case=run_case
    )
    return code, merger, ran


def test_command_case_that_rebased_the_lane_lands_the_tested_head(
    tmp_path: Path, monkeypatch
):
    code, merger, ran = _command_case_merge(tmp_path, monkeypatch)
    assert code == 0
    assert ran == [77]
    merger.assert_called_once()
    assert merger.call_args.kwargs["commit_sha"] == REBASED_SHA


def test_command_case_that_failed_is_not_reported_as_proof(tmp_path: Path, monkeypatch):
    code, merger, ran = _command_case_merge(tmp_path, monkeypatch, verdict="error")
    assert code == 1
    assert ran == [77]
    merger.assert_not_called()


def test_unreadable_recheck_refuses_with_its_recovery(
    tmp_path: Path, monkeypatch, capsys
):
    requirement = _requirement(verdict="pass", sha="")
    requirement.update(method_id="command-ci", runner_id="ci_run")
    item = _item(requirement)
    reads = iter([(item, ""), (None, "control plane unreachable")])
    code, merger = _run_merge(
        tmp_path,
        monkeypatch,
        item,
        rerecord=mock.Mock(),
        run_case=lambda _id, _lane, _sha: None,
        resolve=lambda *_a: next(reads),
    )
    assert code == 1
    error = capsys.readouterr().err
    assert "commit_bound_recheck_unreadable" in error
    assert "control plane unreachable" in error
    assert "retry `yoke merge item YOK-10`" in error
    merger.assert_not_called()


def test_browser_case_refuses_before_fabricating_run(
    tmp_path: Path,
    monkeypatch,
    capsys,
):
    requirement = _requirement(verdict="pass", sha="")
    requirement["method_id"] = "browser-check"
    requirement["runner_id"] = "browser_substrate"
    item = _item(requirement)
    rerecord = mock.Mock()
    run_case = mock.Mock()

    code, merger = _run_merge(
        tmp_path,
        monkeypatch,
        item,
        rerecord=rerecord,
        run_case=run_case,
    )

    assert code == 1
    error = capsys.readouterr().err
    assert "commit_bound_runner_authority" in error
    assert "browser-check" in error
    assert "browser_substrate" in error
    assert "qa_phase=post_deploy" in error
    merger.assert_not_called()
    rerecord.assert_not_called()
    run_case.assert_not_called()


def test_failed_verdict_is_not_a_commit_bound_recovery(tmp_path: Path, monkeypatch):
    item = _item(_requirement(verdict="error", sha=MERGING_SHA))
    rerecord = mock.Mock(side_effect=AssertionError("must not recover"))
    code, merger = _run_merge(tmp_path, monkeypatch, item, rerecord=rerecord)
    assert code == 1
    merger.assert_not_called()
    rerecord.assert_not_called()


@pytest.mark.parametrize("mixed", [False, True])
def test_epic_reviews_use_epic_writer_then_land(tmp_path, monkeypatch, mixed):
    from yoke_core.domain import db_helpers, epic_review, qa_execution

    reviews = [
        dict(
            _requirement(verdict="pass", sha=EARLIER_SHA, requirement_id=number),
            epic_id=10,
            task_num=number - 76,
            item_id=None,
            evidence=f"Complete task review {number}",
        )
        for number in (77, 78)
    ]
    standalone = dict(
        _requirement(verdict="pass", sha=EARLIER_SHA, requirement_id=79),
        item_id=10,
        epic_id=10,
        task_num=3,
        raw_result="Standalone acceptance",
    )
    item = _item(None)
    item["qa_requirements"] = reviews + ([standalone] if mixed else [])
    connection = mock.MagicMock()
    connection.__enter__.return_value = connection
    monkeypatch.setattr(epic_review, "_epic_connect", lambda: connection)
    owners = {
        row["id"]: {key: row.pop(key) for key in ("item_id", "epic_id", "task_num")}
        for row in item["qa_requirements"]
    }
    monkeypatch.setattr(
        db_helpers, "query_one", lambda conn, sql, params: owners[params[0]]
    )
    writer = mock.Mock()
    general = mock.Mock()
    monkeypatch.setattr(epic_review, "review_insert", writer)
    monkeypatch.setattr(qa_execution, "cmd_run_add", general)

    code, merger = _run_merge(
        tmp_path, monkeypatch, item, rerecord=commit_bound.rerecord_hand_run
    )

    assert code == 0
    assert writer.call_args_list == [
        mock.call(
            connection,
            "10",
            number - 76,
            "PASS",
            f"Complete task review {number}",
            head_sha=MERGING_SHA,
        )
        for number in (77, 78)
    ]
    if mixed:
        general.assert_called_once_with(
            requirement_id=79,
            performed_by="agent",
            verdict="pass",
            raw_result="Standalone acceptance",
            head_sha=MERGING_SHA,
        )
    else:
        general.assert_not_called()
    assert all(
        row["recorded_head_sha"] == MERGING_SHA for row in item["qa_requirements"]
    )
    merger.assert_called_once()


@pytest.mark.parametrize("failure", [SystemExit(2), RuntimeError("write refused")])
def test_recovery_reports_all_failed_requirements_and_continues(
    tmp_path, monkeypatch, capsys, failure
):
    import sys

    item = _item(None)
    item["qa_requirements"] = [
        _requirement(verdict="pass", sha=EARLIER_SHA, requirement_id=number)
        for number in range(77, 81)
    ]
    attempted = []

    def rerecord(requirement, commit_sha):
        attempted.append(requirement["id"])
        if requirement["id"] in (78, 79):
            print("writer_refused: repair review evidence", file=sys.stderr)
            raise failure
        commit_bound._mark_bound(requirement, commit_sha)

    code, merger = _run_merge(tmp_path, monkeypatch, item, rerecord=rerecord)

    assert code == 1
    assert attempted == [77, 78, 79, 80]
    error = capsys.readouterr().err
    assert "commit_bound_recovery_failed" in error
    assert "requirement #78: writer_refused: repair review evidence" in error
    assert "requirement #79: writer_refused: repair review evidence" in error
    assert "Recovered requirement ids: 77, 80" in error
    assert "retry `yoke merge item YOK-10`" in error
    assert item["qa_requirements"][1]["recorded_head_sha"] == EARLIER_SHA
    merger.assert_not_called()
