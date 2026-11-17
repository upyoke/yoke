"""Resuming a failed workflow stage dispatches once and joins thereafter.

A fake GitHub stands in for the dispatch intent store: a request id that
already dispatched recovers its run (``recovered``), a new one POSTs
(``dispatched``). Each run has a state the ``poll`` read reports.
"""

from __future__ import annotations

import subprocess
from unittest import mock

import pytest

from yoke_contracts.api.function_call import FunctionCallResponse
from yoke_contracts.github_workflow_dispatch import (
    WORKFLOW_DISPATCH_DISPATCHED_MARKER,
    WORKFLOW_DISPATCH_RECOVERED_MARKER,
)
from yoke_core.domain import (
    deploy_pipeline_bound_inputs,
    deploy_pipeline_github_workflow,
)
from yoke_core.domain.deploy_pipeline_github_workflow_retry import (
    RetryWalkError,
    dispatch_stage,
    walk_failed_stage_dispatch,
)

POLL_RC = {"success": 0, "failed": 1, "in_progress": 2, "queued": 3}
BASE = "deploy:yoke:run-test:hosted-release"
STAGE_CONFIG = {
    "workflow": "consumer-release.yml",
    "dispatch_correlation_input": "yoke_dispatch_id",
    "ref": "main",
    "reconcile_by_head_sha": False,
    "wait_for_ci": False,
    "inputs": {"product_sha": "{head_sha}"},
}


class FakeGitHub:
    """Request ids map to the run they started; runs carry a state."""

    def __init__(self, intents=None, states=None, poll_rc=None):
        self.intents: dict[str, str] = dict(intents or {})
        self.states: dict[str, str] = dict(states or {})
        self.poll_rc = poll_rc
        self.posts: list[str] = []

    def _done(self, args, stdout, stderr=""):
        return subprocess.CompletedProcess(args, 0, stdout=stdout, stderr=stderr)

    def dispatch(self, request_id):
        if request_id in self.intents:
            return self.intents[request_id], False
        run = str(9000 + len(self.posts))
        self.posts.append(request_id)
        self.intents[request_id] = run
        self.states[run] = "in_progress"
        return run, True

    def trigger(self, scope):
        request_id = f"{BASE}:{scope}" if scope else BASE
        run, dispatched = self.dispatch(request_id)
        return self._done([], run), run, dispatched

    def github_actions(self, *args, **_kwargs):
        if args[0] == "poll":
            if self.poll_rc is not None:
                return subprocess.CompletedProcess(args, self.poll_rc, "", "boom")
            state = self.states[args[2]]
            return subprocess.CompletedProcess(args, POLL_RC[state], state, "")
        assert args[0] == "trigger", args
        request_id = args[args.index("--request-id") + 1]
        run, dispatched = self.dispatch(request_id)
        marker = (
            WORKFLOW_DISPATCH_DISPATCHED_MARKER
            if dispatched
            else WORKFLOW_DISPATCH_RECOVERED_MARKER
        )
        return self._done(args, f"{run}\n", marker)


def _walk(github):
    return walk_failed_stage_dispatch(
        github.trigger,
        github_actions=github.github_actions,
        github_repo="upyoke/platform",
        project="yoke",
        sd=None,
    )


def test_a_failed_run_dispatches_exactly_once_and_a_repeat_resume_joins_it():
    github = FakeGitHub(intents={BASE: "100"}, states={"100": "failed"})

    _result, first = _walk(github)

    assert github.posts == [f"{BASE}:retry:100"]
    assert first == github.intents[f"{BASE}:retry:100"]

    _result, second = _walk(github)

    assert second == first
    assert github.posts == [f"{BASE}:retry:100"]


@pytest.mark.parametrize("state", ["in_progress", "queued", "success"])
def test_an_active_or_succeeded_run_is_joined_not_redispatched(state):
    github = FakeGitHub(intents={BASE: "100"}, states={"100": state})

    _result, run = _walk(github)

    assert run == "100"
    assert github.posts == []


def test_a_failed_retry_is_retried_under_its_own_run_id():
    github = FakeGitHub(
        intents={BASE: "100", f"{BASE}:retry:100": "200"},
        states={"100": "failed", "200": "failed"},
    )

    _result, run = _walk(github)

    assert github.posts == [f"{BASE}:retry:200"]
    assert run == github.intents[f"{BASE}:retry:200"]


def test_an_unreadable_run_state_dispatches_nothing_and_names_recovery():
    github = FakeGitHub(intents={BASE: "100"}, states={"100": "failed"}, poll_rc=4)

    with pytest.raises(RetryWalkError, match="restore GitHub Actions read authority"):
        _walk(github)
    assert github.posts == []

    result, run, error = dispatch_stage(
        github.trigger,
        "",
        walk=True,
        github_actions=github.github_actions,
        github_repo="upyoke/platform",
        project="yoke",
        sd=None,
    )
    assert (result, run) == (None, "")
    assert "workflow run 100" in error


def test_an_explicit_scope_or_no_walk_triggers_directly():
    github = FakeGitHub(intents={BASE: "100"}, states={"100": "failed"})
    common = dict(
        github_actions=github.github_actions,
        github_repo="upyoke/platform",
        project="yoke",
        sd=None,
    )

    _r, run, error = dispatch_stage(github.trigger, "", walk=False, **common)
    assert (run, error) == ("100", "")
    _r, run, error = dispatch_stage(github.trigger, "fresh:x", walk=True, **common)
    assert error == "" and github.posts == [f"{BASE}:fresh:x"]


def _stage(github, *, retry_failed):
    with (
        mock.patch.object(
            deploy_pipeline_github_workflow,
            "_run_cmd",
            return_value=subprocess.CompletedProcess([], 0, stdout="a" * 40 + "\n"),
        ),
        mock.patch.object(
            deploy_pipeline_github_workflow,
            "_github_actions",
            side_effect=github.github_actions,
        ),
        mock.patch.object(
            deploy_pipeline_github_workflow,
            "_poll_github_actions",
            side_effect=lambda _repo, run, *_a, **_k: (
                (0, "") if github.states[run] == "success" else (1, "failed")
            ),
        ),
        mock.patch.object(deploy_pipeline_github_workflow, "_emit_run_event"),
        mock.patch.object(
            deploy_pipeline_bound_inputs,
            "call_dispatcher",
            return_value=FunctionCallResponse(
                success=True,
                function="deployment_runs.execution.bound_sources_prepare",
                version="v1",
                result={"bound_sources": {"inputs": {}}, "members": []},
            ),
        ),
    ):
        return deploy_pipeline_github_workflow._dispatch_github_actions_workflow(
            STAGE_CONFIG,
            name="hosted-release",
            run_id="run-test",
            member_items=[],
            github_repo="upyoke/platform",
            project="yoke",
            project_repo_path="",
            timeout_min=30,
            fresh=False,
            retry_failed=retry_failed,
            gate_branch="main",
            release_lineage="a" * 40,
            sd="/tmp/sd",
        )


def test_resuming_the_failed_stage_dispatches_once_where_a_redrive_replays():
    github = FakeGitHub(intents={BASE: "100"}, states={"100": "failed"})

    assert _stage(github, retry_failed=False) == (1, "failed")
    assert github.posts == []

    new_run = None

    def succeed_new_runs(*args, **kwargs):
        result = FakeGitHub.github_actions(github, *args, **kwargs)
        if WORKFLOW_DISPATCH_DISPATCHED_MARKER in (result.stderr or ""):
            nonlocal new_run
            new_run = result.stdout.strip()
            github.states[new_run] = "success"
        return result

    github.github_actions = succeed_new_runs
    assert _stage(github, retry_failed=True) == (0, "")
    assert github.posts == [f"{BASE}:retry:100"]
    assert github.intents[f"{BASE}:retry:100"] == new_run

    assert _stage(github, retry_failed=True) == (0, "")
    assert github.posts == [f"{BASE}:retry:100"]
