"""Proof of one exact commit is shared by merge verification and delivery."""

from __future__ import annotations

from unittest import mock

import pytest

from runtime.api.domain.test_deployment_run_ci_tested_source import (
    HEAD,
    MIDDLE,
    OLDEST,
    TARGET,
    _github,
    _run,
)
from yoke_core.domain import ci_commit_proof as proof
from yoke_core.domain import deployment_run_ci_tested_source as tested
from yoke_core.domain import deployment_run_gate_branch_lineage as lineage
from yoke_core.domain.github_actions_rest import latest_workflow_run


@pytest.fixture
def gated():
    with (
        mock.patch.object(tested, "ci_gate_target", return_value=TARGET),
        mock.patch.object(lineage, "previous_release", return_value=None),
    ):
        yield

def test_proof_needs_the_exact_commit_and_an_eligible_event():
    assert proof.proves(_run(HEAD, "completed", "success", 1, branch="lane"), HEAD)
    assert not proof.proves(_run(MIDDLE, "completed", "success", 1), HEAD)
    for event in ("pull_request", "pull_request_target", "merge_group"):
        assert not proof.proves(_run(HEAD, "completed", "success", 1, event=event), HEAD)


def test_the_newest_eligible_attempt_answers_whatever_its_state():
    older_green = {**_run(HEAD, "completed", "success", 7), "run_attempt": 1}
    newer_attempt = {**older_green, "run_attempt": 2, "status": "in_progress"}
    foreign = _run(HEAD, "completed", "success", 9, event="pull_request")
    assert proof.proof_run([older_green, newer_attempt, foreign], HEAD) is newer_attempt
    assert proof.proof_run([older_green, newer_attempt], HEAD, exclude_run_id="7") is None


def test_a_branchless_commit_lookup_answers_with_the_proof_run():
    runs = [
        _run(HEAD, "completed", "success", 4, event="pull_request"),
        _run(HEAD, "completed", "failure", 3, event="workflow_dispatch", branch="lane"),
    ]
    with mock.patch(
        "yoke_core.domain.github_actions_rest.rest_get",
        return_value={"workflow_runs": runs},
    ):
        found = latest_workflow_run("o/r", "ci.yml", head_sha=HEAD, token="t")
        on_branch = latest_workflow_run("o/r", "ci.yml", branch="main", head_sha=HEAD, token="t")
    assert found["id"] == 3
    assert on_branch["id"] == 4


def test_flow_without_ci_wait_binds_the_tip_without_reading_runs():
    target = tested.CiGateTarget("p", "f", "owner/p", "", "main", "token")
    with (
        mock.patch.object(tested, "ci_gate_target", return_value=target),
        mock.patch.object(lineage, "previous_release", return_value=None),
        mock.patch.object(tested, "gate_branch_tip", return_value=HEAD),
        mock.patch.object(tested, "_read") as read,
        mock.patch.object(tested, "dispatch_branch_ci") as dispatch,
    ):
        assert tested.bind_tested_release_source("p", "f", None, None) == HEAD
        assert tested.bind_tested_release_source("p", "f", None, OLDEST) == OLDEST

    read.assert_not_called()
    dispatch.assert_not_called()


@pytest.mark.parametrize("event", ["workflow_dispatch", "push"])
def test_tip_proven_on_another_branch_is_reused_without_dispatch(gated, event):
    # Merge verification dispatched the suite on the lane branch; the same
    # commit is now the gate branch tip.
    runs = [_run(HEAD, "completed", "success", 3, event=event, branch="PLAT-258")]
    with (
        mock.patch.object(tested, "_read", side_effect=_github(runs)),
        mock.patch.object(tested, "dispatch_branch_ci") as dispatch,
    ):
        assert tested.bind_tested_release_source("platform", "flow", None, None) == HEAD
        assert tested.bind_tested_release_source("platform", "flow", None, HEAD) == HEAD
    dispatch.assert_not_called()


def test_a_newer_failed_attempt_on_another_branch_beats_an_older_green(gated):
    runs = [
        _run(HEAD, "completed", "success", 2),
        _run(HEAD, "completed", "failure", 5, event="workflow_dispatch", branch="lane"),
    ]
    with (
        mock.patch.object(tested, "_read", side_effect=_github(runs)),
        pytest.raises(tested.ReleaseSourceRefused) as refused,
    ):
        tested.bind_tested_release_source("platform", "flow", None, None)
    assert refused.value.code == "release_source_ci_failed"


def test_a_green_run_on_another_commit_never_proves_the_tip(gated):
    runs = [{**_run(MIDDLE, "completed", "success", 4), "head_sha": MIDDLE}]
    with (
        mock.patch.object(tested, "_read", return_value={"workflow_runs": runs}),
        mock.patch.object(tested, "gate_branch_tip", return_value=HEAD),
        mock.patch.object(tested, "dispatch_branch_ci", return_value=HEAD) as dispatch,
    ):
        assert tested.bind_tested_release_source("platform", "flow", None, None) == HEAD
    dispatch.assert_called_once_with(TARGET)
