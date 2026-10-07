"""Where a github-actions-workflow stage is dispatched, and its declaration."""

from __future__ import annotations

import json
import subprocess

import pytest

from yoke_core.domain import deploy_pipeline_github_workflow as workflow_stage
from yoke_core.domain.deploy_pipeline_release_commit_ref import dispatch_ref
from yoke_core.domain.flow_validation import validate_stages


SHA = "c" * 40
RUN = "run-20261007-021"


def _ref(config, *, head_sha=SHA, returncode=0, stderr=""):
    calls = []

    def github_actions(*args, project, sd):
        calls.append(args)
        return subprocess.CompletedProcess(list(args), returncode, "", stderr)

    result = dispatch_ref(
        config, name="hosted-stage", run_id=RUN, github_repo="owner/app",
        head_sha=head_sha, project="app", sd=None, github_actions=github_actions,
    )
    return result, calls


def test_an_undeclared_stage_dispatches_at_its_branch_untouched() -> None:
    assert _ref({"ref": "release"}) == (("release", ""), [])
    assert _ref({}) == (("main", ""), [])


def test_a_declared_stage_dispatches_at_the_run_tag_on_its_release_commit() -> None:
    (ref, refusal), calls = _ref({"run_from_release_commit": True})

    assert (ref, refusal) == (f"yoke-deploy/{RUN}", "")
    assert calls == [
        ("dispatch-tag", "ensure", "owner/app", f"yoke-deploy/{RUN}", SHA)
    ]


def test_a_refused_tag_stops_the_stage_with_the_named_reason() -> None:
    (ref, refusal), _calls = _ref(
        {"run_from_release_commit": True},
        returncode=1,
        stderr="dispatch_tag_conflict: tag already names another commit",
    )

    assert ref == ""
    assert "was not dispatched" in refusal
    assert "dispatch_tag_conflict" in refusal
    assert f"re-drive {RUN}" in refusal


def test_a_declared_stage_without_a_full_commit_never_tags() -> None:
    (ref, refusal), calls = _ref({"run_from_release_commit": True}, head_sha="")

    assert ref == "" and "no full release commit" in refusal
    assert calls == []


def test_the_stage_runner_dispatches_at_the_tag(monkeypatch) -> None:
    seen = {}
    monkeypatch.setattr(
        workflow_stage, "_resolve_release_lineage_sha", lambda *a: (SHA, "")
    )
    monkeypatch.setattr(
        workflow_stage,
        "_github_actions",
        lambda *args, project, sd: subprocess.CompletedProcess(args, 0, "", ""),
    )

    def trigger(**kwargs):
        seen["ref"] = kwargs["workflow_ref"]
        return subprocess.CompletedProcess([], 1, "", "stop here"), "", False

    monkeypatch.setattr(workflow_stage, "run_correlated_or_oneshot_trigger", trigger)

    rc, _diagnostic = workflow_stage._dispatch_github_actions_workflow(
        {
            "workflow": "release.yml",
            "dispatch_correlation_input": "yoke_dispatch_id",
            "inputs": {"app_ref": "{head_sha}"},
            "wait_for_ci": False,
            "run_from_release_commit": True,
        },
        name="hosted-stage", run_id=RUN, member_items=[], github_repo="owner/app",
        project="app", project_repo_path="/tmp", timeout_min=1, fresh=False,
        gate_branch="main", release_lineage=SHA, sd="/tmp",
    )

    assert rc == 1
    assert seen["ref"] == f"yoke-deploy/{RUN}"


def _stages(**stage_fields) -> str:
    stage = {"name": "deploy", "step_runner": "github-actions-workflow",
             "workflow": "release.yml", **stage_fields}
    return json.dumps([stage])


def test_validation_accepts_the_declared_key() -> None:
    validate_stages(_stages(run_from_release_commit=True))
    validate_stages(_stages(run_from_release_commit=False, ref="main"))


@pytest.mark.parametrize(
    "stages,message",
    [
        (_stages(run_from_release_commit="yes"), "must be a boolean"),
        (_stages(run_from_release_commit=True, ref="main"), 'remove "ref"'),
        (
            json.dumps([{"name": "x", "step_runner": "auto",
                         "run_from_release_commit": True}]),
            "applies only to",
        ),
    ],
)
def test_validation_refuses_a_misdeclared_key(stages, message) -> None:
    with pytest.raises(ValueError, match=message):
        validate_stages(stages)
