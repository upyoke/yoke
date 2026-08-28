"""Adopting or attaching to the run that already covers this commit.

The lookup and classifier are exercised directly, then driven through
``execute_ci_case`` so the runner's three paths — adopt, attach, dispatch
— are covered where they are actually chosen.
"""

from __future__ import annotations

import json
import subprocess
from unittest import mock

import pytest

from runtime.api.domain.qa_case_ci_test_helpers import (
    LANE_HEAD,
    ci_case,
    completed_run,
    in_flight_run,
    wire_ci_case,
)

from yoke_core.domain import (
    qa_case_ci_covering_run as covering,
    qa_case_ci_lane,
    qa_case_ci_run,
)
from yoke_core.domain.qa_case_execution import QaCaseExecutionError


@pytest.fixture()
def wired(tmp_path, monkeypatch):
    return wire_ci_case(tmp_path, monkeypatch)


def _found(**overrides) -> dict:
    payload = {
        "found": True,
        "run_id": "77",
        "status": "completed",
        "conclusion": "success",
        "html_url": "https://github.test/actions/runs/77",
        "head_sha": LANE_HEAD,
    }
    payload.update(overrides)
    return {"result": payload}


def _stub_lookup(monkeypatch, body: dict, returncode: int = 0) -> dict:
    seen: dict = {}

    def _github_actions(*args, **kwargs):
        seen.update(args=args, kwargs=kwargs)
        return subprocess.CompletedProcess(
            list(args), returncode, json.dumps(body), "",
        )

    monkeypatch.setattr(
        "yoke_core.domain.deploy_pipeline_reporting._github_actions",
        _github_actions,
    )
    return seen


# The lookup


def test_the_lookup_asks_about_the_commit_not_about_how_a_run_started(
    monkeypatch,
):
    """A run this gate dispatched and lost is still evidence about this tree."""
    seen = _stub_lookup(monkeypatch, _found())

    run = covering.find_run_for_tree(
        project="yoke", repo="acme/widgets", workflow="ci.yml",
        head_sha=LANE_HEAD, timeout_seconds=60,
    )

    assert run == completed_run(LANE_HEAD)
    assert seen["args"] == (
        "find-run", "acme/widgets", "ci.yml", LANE_HEAD, "--json",
    )


@pytest.mark.parametrize(
    ("filters", "expected"),
    [
        ({"event": "pull_request"}, ("--event", "pull_request")),
        ({"status": "completed"}, ("--status", "completed")),
    ],
)
def test_narrowing_filters_reach_the_lookup(monkeypatch, filters, expected):
    seen = _stub_lookup(monkeypatch, _found())

    covering.find_run_for_tree(
        project="yoke", repo="acme/widgets", workflow="ci.yml",
        head_sha=LANE_HEAD, timeout_seconds=60, **filters,
    )

    assert seen["args"] == (
        "find-run", "acme/widgets", "ci.yml", LANE_HEAD, *expected, "--json",
    )


def test_an_untested_commit_answers_none(monkeypatch):
    _stub_lookup(monkeypatch, {"result": {"found": False}}, returncode=1)

    assert covering.find_run_for_tree(
        project="yoke", repo="acme/widgets", workflow="ci.yml",
        head_sha=LANE_HEAD, timeout_seconds=60,
    ) is None


def test_a_failed_lookup_refuses_rather_than_reporting_no_run(monkeypatch):
    """Silently answering "none" here would dispatch a duplicate run."""
    _stub_lookup(monkeypatch, {"error": "relay down"}, returncode=2)

    with pytest.raises(QaCaseExecutionError, match="could not query workflow"):
        covering.find_run_for_tree(
            project="yoke", repo="acme/widgets", workflow="ci.yml",
            head_sha=LANE_HEAD, timeout_seconds=60,
        )


# The classifier


@pytest.mark.parametrize(
    ("run", "expected"),
    [
        (None, covering.DISPATCHED),
        (completed_run(LANE_HEAD), covering.ADOPTED),
        (completed_run(LANE_HEAD, "failure"), covering.ADOPTED),
        (completed_run(LANE_HEAD, "cancelled"), covering.DISPATCHED),
        (completed_run(LANE_HEAD, "timed_out"), covering.DISPATCHED),
        (completed_run("b" * 40), covering.DISPATCHED),
        (in_flight_run(LANE_HEAD), covering.ATTACHED),
        (in_flight_run(LANE_HEAD, "queued"), covering.ATTACHED),
        (in_flight_run("b" * 40), covering.DISPATCHED),
    ],
)
def test_classify_names_what_the_run_lets_this_invocation_do(run, expected):
    assert covering.classify(run, head_sha=LANE_HEAD) == expected


def test_a_run_with_no_reported_sha_is_never_adopted():
    """Exact-SHA matching cannot be satisfied by a missing SHA."""
    blank = qa_case_ci_lane.WorkflowRun(
        "77", "completed", "success", "https://github.test/runs/77", "",
    )

    assert covering.classify(blank, head_sha=LANE_HEAD) == covering.DISPATCHED


# The runner's three paths


@pytest.mark.parametrize(
    ("conclusion", "verdict"), [("success", "pass"), ("failure", "fail")],
)
def test_a_concluded_run_is_adopted_without_dispatching_or_polling(
    wired, monkeypatch, conclusion, verdict,
):
    """The killed-watcher recovery: the verdict costs one lookup, not a suite."""
    checkout, recorder, _ = wired
    monkeypatch.setattr(
        covering, "find_run_for_tree",
        lambda **k: completed_run(LANE_HEAD, conclusion),
    )
    dispatch = mock.Mock(side_effect=AssertionError("must not dispatch"))
    await_run = mock.Mock(side_effect=AssertionError("must not poll"))
    monkeypatch.setattr(qa_case_ci_lane, "dispatch_workflow", dispatch)
    monkeypatch.setattr(qa_case_ci_lane, "await_workflow", await_run)

    result = qa_case_ci_run.execute_ci_case(ci_case(), checkout_path=checkout)

    assert result["verdict"] == verdict
    assert result["ci_run_source"] == "adopted"
    assert result["ci_run_id"] == "77"
    assert result["run_url"] == "https://github.test/actions/runs/77"
    evidence = json.loads(recorder.payload("qa.run.add")["raw_result"])
    assert evidence["ci_run_source"] == "adopted"
    assert evidence["ci_run_id"] == "77"
    dispatch.assert_not_called()
    await_run.assert_not_called()


def test_an_in_flight_run_is_polled_instead_of_duplicated(wired, monkeypatch):
    checkout, recorder, _ = wired
    monkeypatch.setattr(
        covering, "find_run_for_tree", lambda **k: in_flight_run(LANE_HEAD),
    )
    dispatch = mock.Mock(side_effect=AssertionError("must not dispatch"))
    monkeypatch.setattr(qa_case_ci_lane, "dispatch_workflow", dispatch)
    awaited: dict = {}
    monkeypatch.setattr(
        qa_case_ci_lane, "await_workflow",
        lambda **k: awaited.update(k) or (0, "success"),
    )

    result = qa_case_ci_run.execute_ci_case(ci_case(), checkout_path=checkout)

    assert result["ci_run_source"] == "attached"
    assert result["verdict"] == "pass"
    assert awaited["run_id"] == "77"
    evidence = json.loads(recorder.payload("qa.run.add")["raw_result"])
    assert evidence["ci_run_source"] == "attached"
    dispatch.assert_not_called()


def test_an_unexamined_commit_still_dispatches(wired, monkeypatch):
    checkout, recorder, _ = wired
    monkeypatch.setattr(covering, "find_run_for_tree", lambda **k: None)
    monkeypatch.setattr(
        qa_case_ci_lane, "dispatch_workflow", lambda **k: "9182736",
    )
    monkeypatch.setattr(
        qa_case_ci_lane, "await_workflow", lambda **k: (0, "success"),
    )

    result = qa_case_ci_run.execute_ci_case(ci_case(), checkout_path=checkout)

    assert result["ci_run_source"] == "dispatched"
    assert result["ci_run_id"] == "9182736"
    evidence = json.loads(recorder.payload("qa.run.add")["raw_result"])
    assert evidence["ci_run_source"] == "dispatched"


def test_an_adopted_run_names_its_provenance_in_the_captured_output(
    wired, monkeypatch,
):
    checkout, _, artifact = wired
    monkeypatch.setattr(
        covering, "find_run_for_tree", lambda **k: completed_run(LANE_HEAD),
    )
    monkeypatch.setattr(
        qa_case_ci_lane, "dispatch_workflow",
        mock.Mock(side_effect=AssertionError("must not dispatch")),
    )

    qa_case_ci_run.execute_ci_case(ci_case(), checkout_path=checkout)

    assert "adopted completed run: success" in artifact.read_text(
        encoding="utf-8",
    )


def test_a_lookup_failure_records_a_run_before_refusing(wired, monkeypatch):
    checkout, recorder, _ = wired

    def _raise(**kwargs):
        raise QaCaseExecutionError("relay down")

    monkeypatch.setattr(covering, "find_run_for_tree", _raise)

    with pytest.raises(QaCaseExecutionError, match="recorded QA run #77"):
        qa_case_ci_run.execute_ci_case(ci_case(), checkout_path=checkout)

    evidence = json.loads(recorder.payload("qa.run.complete")["raw_result"])
    assert evidence["ci_run_source"] == "dispatched"
    assert evidence["ci_run_id"] is None
