"""Required checks whose only red step was a runner-capacity refusal."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from yoke_core.domain import merge_queue_capacity_checks as capacity
from yoke_core.domain.gh_rest_transport import RestTransportError
from yoke_core.domain.merge_context import MergeArgs, MergeContext
from yoke_core.domain.merge_github_check_runs import LandingCheck

CTX = MergeContext(args=MergeArgs(branch="ALP-1"), repo_root="", project="alpha")
JOB_URL = "https://github.com/o/r/actions/runs/{run}/job/{job}"


def _check(name, job, *, run=7, conclusion="failure", url=None, required=True):
    return LandingCheck(
        name=name,
        status="completed",
        conclusion=conclusion,
        required=required,
        url=url if url is not None else JOB_URL.format(run=run, job=job),
    )


def _job(job_id, *red_steps, conclusion="failure"):
    return {
        "id": job_id,
        "runner_name": "runner",
        "conclusion": conclusion,
        "steps": [{"name": "Checkout", "conclusion": "success"}]
        + [{"name": name, "conclusion": "failure"} for name in red_steps],
    }


@pytest.fixture
def github(monkeypatch):
    state = {"jobs": {}, "reads": [], "auth_error": None, "list_error": None}

    def resolve(_ctx, _perms):
        if state["auth_error"]:
            return None, state["auth_error"]
        return SimpleNamespace(repo="o/r", token="tok"), None

    def list_jobs(repo, run_id, *, token):
        state["reads"].append((repo, str(run_id), token))
        if state["list_error"]:
            raise state["list_error"]
        return state["jobs"].get(str(run_id), [])

    monkeypatch.setattr(capacity, "resolve_auth_detail", resolve)
    monkeypatch.setattr(capacity, "list_run_jobs", list_jobs)
    return state


def test_capacity_only_job_is_rewritten_and_any_other_red_step_is_kept(github):
    github["jobs"]["7"] = [
        _job(1, "Check runner capacity"),
        _job(2, "Check runner capacity", "Run pytest"),
        _job(3, "Run pytest"),
    ]
    checks = (_check("a", 1), _check("b", 2), _check("c", 3))

    got = capacity.with_capacity_refusals(CTX, checks)

    assert [check.conclusion for check in got] == [
        capacity.CAPACITY_REFUSED, "failure", "failure"]
    assert got[0].url == checks[0].url and got[0].name == "a"


def test_jobs_are_read_once_per_distinct_run(github):
    github["jobs"]["7"] = [_job(1, "Check runner capacity"), _job(2, "Check runner capacity")]
    github["jobs"]["8"] = [_job(3, "Check runner capacity")]

    got = capacity.with_capacity_refusals(
        CTX, (_check("a", 1), _check("b", 2), _check("c", 3, run=8)))

    assert {check.conclusion for check in got} == {capacity.CAPACITY_REFUSED}
    assert github["reads"] == [("o/r", "7", "tok"), ("o/r", "8", "tok")]


@pytest.mark.parametrize("failure", ["auth", "listing", "missing_job"])
def test_unreadable_job_evidence_keeps_githubs_conclusion(github, failure):
    if failure == "auth":
        github["auth_error"] = "Actions read not granted"
    elif failure == "listing":
        github["list_error"] = RestTransportError("503")
    else:
        github["jobs"]["7"] = [_job(99, "Check runner capacity")]
    check = _check("a", 1)

    assert capacity.with_capacity_refusals(CTX, (check,)) == (check,)


@pytest.mark.parametrize(
    "check",
    [
        _check("status", 1, url="https://ci.example/build/1"),
        _check("run-only", 1, url="https://github.com/o/r/actions/runs/7"),
        _check("other-repo", 1, url="https://github.com/x/y/actions/runs/7/job/1"),
        _check("optional", 1, required=False),
        _check("cancelled", 1, conclusion="cancelled"),
        _check("green", 1, conclusion="success"),
    ],
)
def test_checks_not_naming_a_red_required_actions_job_are_untouched(github, check):
    github["jobs"]["7"] = [_job(1, "Check runner capacity")]

    assert capacity.with_capacity_refusals(CTX, (check,)) == (check,)


def test_no_candidate_reads_nothing(github):
    github["auth_error"] = "must not be resolved"

    assert capacity.with_capacity_refusals(CTX, ()) == ()
    assert github["reads"] == []


def test_landing_read_reports_the_capacity_refusal(github, monkeypatch):
    from runtime.api.engines.merge_worktree_pr_check_runs_test_support import (
        _check_run, _ctx, _pr_node, _wire,
    )
    from yoke_core.domain import merge_github_check_runs as checks_mod

    node = _check_run(name="test-shard (3.11, 12)", status="COMPLETED", conclusion="FAILURE")
    node["detailsUrl"] = JOB_URL.format(run=7, job=1)
    _wire(monkeypatch, _pr_node(contexts=(node,)))
    github["jobs"]["7"] = [_job(1, "Check runner capacity")]

    projection = checks_mod.read_pr_landing_and_required_checks(_ctx(), "42")

    assert [check.conclusion for check in projection.required_checks] == [
        capacity.CAPACITY_REFUSED]
