"""Empty-diff command-ci lanes record a pass instead of erroring."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest import mock

import pytest

from runtime.api.domain.qa_case_ci_test_helpers import (
    LANE_HEAD,
    ci_case,
    wire_ci_case,
)

from yoke_core.domain import (
    qa_case_ci_empty_diff as empty_diff,
    qa_case_ci_lane,
    qa_case_ci_run,
)


@pytest.fixture()
def wired(tmp_path, monkeypatch):
    return wire_ci_case(tmp_path, monkeypatch)


def _run(checkout, *, dispatch=None, await_result=None):
    dispatch = dispatch or mock.Mock(side_effect=AssertionError("dispatch"))
    await_result = await_result or mock.Mock(side_effect=AssertionError("await"))
    with mock.patch.object(qa_case_ci_lane, "dispatch_workflow", dispatch):
        with mock.patch.object(qa_case_ci_lane, "await_workflow", await_result):
            return qa_case_ci_run.execute_ci_case(
                ci_case(),
                checkout_path=checkout,
            )


def test_lane_on_target_has_no_commits_against_target(git_repo: Path) -> None:
    subprocess.run(
        ["git", "-C", str(git_repo), "checkout", "-qb", "YOK-empty"],
        check=True,
        capture_output=True,
    )
    assert empty_diff.lane_has_no_commits_against_target(git_repo, "main") is True


def test_lane_with_its_own_commit_is_not_empty(git_repo: Path) -> None:
    subprocess.run(
        ["git", "-C", str(git_repo), "checkout", "-qb", "YOK-ahead"],
        check=True,
        capture_output=True,
    )
    (git_repo / "extra.txt").write_text("ahead\n")
    subprocess.run(
        ["git", "-C", str(git_repo), "add", "extra.txt"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(git_repo), "commit", "-q", "-m", "ahead"],
        check=True,
        capture_output=True,
    )
    assert empty_diff.lane_has_no_commits_against_target(git_repo, "main") is False


def test_empty_diff_records_pass_without_push_or_dispatch(
    wired,
    monkeypatch,
) -> None:
    checkout, recorder, _ = wired
    monkeypatch.setattr(
        empty_diff,
        "lane_has_no_commits_against_target",
        lambda *_a, **_k: True,
    )
    monkeypatch.setattr(empty_diff, "_lookup_covering_run", lambda **_k: None)
    push = mock.Mock(side_effect=AssertionError("must not push"))
    monkeypatch.setattr(qa_case_ci_lane, "push_lane", push)

    result = _run(checkout)

    assert result["verdict"] == "pass"
    assert result["case_outcome"] == "passed"
    assert result["empty_diff"] is True
    assert result["verification_tree"]["head_sha"] == LANE_HEAD
    evidence = json.loads(recorder.payload("qa.run.add")["raw_result"])
    assert evidence["empty_diff"] is True
    assert evidence["verification_tree"]["head_sha"] == LANE_HEAD
    assert evidence["ci_conclusion"] == "success"
    assert recorder.payload("qa.run.complete")["verdict"] == "pass"
    push.assert_not_called()


def test_empty_diff_cites_covering_run_for_the_tree_sha(
    wired,
    monkeypatch,
) -> None:
    checkout, recorder, _ = wired
    covering = qa_case_ci_lane.WorkflowRun(
        "91",
        "completed",
        "success",
        "https://github.test/actions/runs/91",
        LANE_HEAD,
    )
    monkeypatch.setattr(
        empty_diff,
        "lane_has_no_commits_against_target",
        lambda *_a, **_k: True,
    )
    monkeypatch.setattr(empty_diff, "_lookup_covering_run", lambda **_k: covering)
    monkeypatch.setattr(
        qa_case_ci_lane,
        "push_lane",
        mock.Mock(side_effect=AssertionError("must not push")),
    )

    result = _run(checkout)

    assert result["verdict"] == "pass"
    assert result["ci_run_id"] == "91"
    assert result["run_url"] == covering.html_url
    evidence = json.loads(recorder.payload("qa.run.add")["raw_result"])
    assert evidence["ci_run_id"] == "91"
    assert evidence["verification_tree"]["head_sha"] == LANE_HEAD


def test_empty_diff_cites_red_covering_run_and_still_passes(
    wired,
    monkeypatch,
) -> None:
    checkout, recorder, _ = wired
    covering = qa_case_ci_lane.WorkflowRun(
        "92",
        "completed",
        "failure",
        "https://github.test/actions/runs/92",
        LANE_HEAD,
    )
    monkeypatch.setattr(
        empty_diff,
        "lane_has_no_commits_against_target",
        lambda *_a, **_k: True,
    )
    monkeypatch.setattr(empty_diff, "_lookup_covering_run", lambda **_k: covering)
    monkeypatch.setattr(
        qa_case_ci_lane,
        "push_lane",
        mock.Mock(side_effect=AssertionError("must not push")),
    )

    result = _run(checkout)

    assert result["verdict"] == "pass"
    assert result["ci_run_id"] == "92"
    evidence = json.loads(recorder.payload("qa.run.add")["raw_result"])
    assert evidence["empty_diff"] is True
    assert evidence["ci_conclusion"] == "success"
    assert recorder.payload("qa.run.complete")["verdict"] == "pass"


def test_non_empty_lane_still_dispatches(wired, monkeypatch) -> None:
    checkout, recorder, _ = wired
    monkeypatch.setattr(
        empty_diff,
        "lane_has_no_commits_against_target",
        lambda *_a, **_k: False,
    )
    result = _run(
        checkout,
        dispatch=lambda **_k: "9182736",
        await_result=lambda **_k: (0, "success"),
    )
    assert result["verdict"] == "pass"
    assert result["ci_run_id"] == "9182736"
    evidence = json.loads(recorder.payload("qa.run.add")["raw_result"])
    assert "empty_diff" not in evidence
