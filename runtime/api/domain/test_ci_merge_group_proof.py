"""Flow-scoped identical-commit queue proof preserves ordinary CI authority."""

import json
from dataclasses import replace
from unittest import mock

import pytest

from yoke_core.domain.ci_commit_proof import proof_run
from yoke_core.domain import deploy_pipeline_queue_ci as queue
from yoke_core.domain import deployment_run_ci_tested_source as tested
from yoke_core.domain.flow_validation import validate_stages
from runtime.api.domain.deployment_run_ci_tested_source_test_support import (
    HEAD,
    TARGET,
    _run,
)


def run(event="merge_group", conclusion="success", **kwargs):
    return _run(HEAD, "completed", conclusion, 10, event=event) | kwargs


def test_queue_proof_requires_opt_in_and_exact_commit():
    green = run()
    assert proof_run([green], HEAD) is None
    assert proof_run([green], HEAD, allow_merge_group=True) == green
    assert proof_run([green], "a" * 40, allow_merge_group=True) is None


@pytest.mark.parametrize("conclusion", ["failure", "cancelled", "skipped", None])
def test_non_success_queue_is_ignored(conclusion):
    assert proof_run([run(conclusion=conclusion)], HEAD, allow_merge_group=True) is None


@pytest.mark.parametrize("event", ["pull_request", "pull_request_target"])
def test_pr_runs_never_prove_commit(event):
    assert proof_run([run(event)], HEAD, allow_merge_group=True) is None


def test_pending_queue_is_ignored():
    assert proof_run([run(status="in_progress")], HEAD, allow_merge_group=True) is None


@pytest.mark.parametrize("conclusion", ["success", "failure", "cancelled"])
def test_ordinary_run_takes_precedence_even_when_older(conclusion):
    push = run("push", conclusion, id=1, run_number=1)
    assert proof_run([push, run()], HEAD, allow_merge_group=True) == push


def test_queue_gate_names_bound_proof_and_needs_no_dispatch():
    with mock.patch.object(queue, "matching_runs", return_value=[run()]):
        passed, message = queue.queue_ci_proof("project", HEAD, "ci.yml")
    assert passed
    assert "merge_group run 10" in message
    assert "no CI dispatch needed" in message


@pytest.mark.parametrize("runs", [[run(conclusion="failure")], [run("push"), run()]])
def test_gate_defers_to_ordinary_path(runs):
    with mock.patch.object(queue, "matching_runs", return_value=runs):
        assert queue.queue_ci_proof("project", HEAD, "ci.yml") is None


def test_gate_read_failure_is_named_with_recovery():
    with mock.patch.object(
        queue, "matching_runs", side_effect=queue.CommitRunAuthorityError("unavailable")
    ):
        passed, message = queue.queue_ci_proof("project", HEAD, "ci.yml")
    assert not passed
    assert "Repair" in message


@pytest.mark.parametrize("enabled", [False, True])
def test_release_creation_uses_flow_opt_in(enabled):
    target = replace(TARGET, allow_merge_group_ci=enabled)
    with mock.patch.object(tested, "_read", return_value={"workflow_runs": [run()]}):
        assert tested._proof_state(target, HEAD) == ("passed" if enabled else "no_runs")


@pytest.mark.parametrize("enabled", [False, True])
def test_release_creation_dispatches_after_unsuccessful_queue(enabled):
    target = replace(TARGET, allow_merge_group_ci=enabled)
    with (
        mock.patch.object(tested, "ci_gate_target", return_value=target),
        mock.patch.object(tested, "gate_branch_tip", return_value=HEAD),
        mock.patch.object(
            tested,
            "_read",
            return_value={"workflow_runs": [run(conclusion="cancelled")]},
        ),
        mock.patch.object(tested, "dispatch_branch_ci", return_value=HEAD) as dispatch,
        mock.patch.object(tested, "require_descends_from_previous_release"),
    ):
        assert (
            tested.bind_tested_release_source("project", "flow", "prod", None) == HEAD
        )
    dispatch.assert_called_once_with(target)


def test_release_creation_reuses_successful_queue_without_dispatch():
    target = replace(TARGET, allow_merge_group_ci=True)
    with (
        mock.patch.object(tested, "ci_gate_target", return_value=target),
        mock.patch.object(tested, "gate_branch_tip", return_value=HEAD),
        mock.patch.object(tested, "_read", return_value={"workflow_runs": [run()]}),
        mock.patch.object(tested, "dispatch_branch_ci") as dispatch,
        mock.patch.object(tested, "require_descends_from_previous_release") as ancestry,
    ):
        assert (
            tested.bind_tested_release_source("project", "flow", "prod", None) == HEAD
        )
    dispatch.assert_not_called()
    ancestry.assert_called_once()


@pytest.mark.parametrize("value", ["true", 1, None])
def test_stage_setting_rejects_non_boolean(value):
    with pytest.raises(ValueError, match="allow_merge_group_ci.*boolean"):
        validate_stages(
            json.dumps(
                [
                    {
                        "name": "deploy",
                        "step_runner": "github-actions-workflow",
                        "allow_merge_group_ci": value,
                    }
                ]
            )
        )


def test_deploy_gate_uses_flow_opt_in_only():
    from yoke_core.domain import deploy_pipeline_gates as gates

    with (
        mock.patch.object(gates, "project_ci_workflow_file", return_value="ci.yml"),
        mock.patch.object(
            queue, "queue_ci_proof", return_value=(True, "queue run 10")
        ) as proof,
        mock.patch.object(gates, "_github_actions") as adapter,
    ):
        assert gates._check_ci_gate(
            "owner/repo",
            "project",
            10,
            branch="main",
            head_sha=HEAD,
            allow_merge_group_ci=True,
        ) == (True, "queue run 10")
        proof.assert_called_once_with("project", HEAD, "ci.yml")
        adapter.assert_not_called()


@pytest.mark.parametrize("enabled", [False, True])
def test_target_reads_setting_from_ci_waiting_stages(enabled):
    from types import SimpleNamespace

    stages = [
        {"step_runner": "github-actions-workflow", "allow_merge_group_ci": enabled}
    ]
    with (
        mock.patch.object(
            tested, "_flow_facts", return_value=(stages, "persistent", "prod")
        ),
        mock.patch(
            "yoke_core.domain.project_renderer_settings.project_ci_workflow_file",
            return_value="ci.yml",
        ),
        mock.patch(
            "yoke_core.domain.project_checkout_locations.checkout_for_project_slug",
            return_value=None,
        ),
        mock.patch(
            "yoke_core.domain.deploy_pipeline_gates.resolve_flow_gate_branch",
            return_value="main",
        ),
        mock.patch.object(
            tested,
            "_auth",
            return_value=SimpleNamespace(repo="owner/repo", token="token"),
        ),
    ):
        assert (
            tested.ci_gate_target("project", "flow", "prod").allow_merge_group_ci
            is enabled
        )
