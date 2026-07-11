"""Same-intent recovery retries for input-bearing workflow dispatch."""

from __future__ import annotations

import subprocess
from unittest import mock

from yoke_core.domain import deploy_pipeline_github_workflow as workflow
from yoke_core.domain import deploy_pipeline_github_workflow_dispatch as retry


def _result(returncode: int, stdout: str = "", stderr: str = ""):
    return subprocess.CompletedProcess([], returncode, stdout, stderr)


def test_ambiguous_then_recovered_trigger_reuses_one_logical_dispatch() -> None:
    calls: list[tuple[str, ...]] = []

    def _github_actions(*args: str, **kwargs):
        calls.append(args)
        trigger_count = sum(call[0] == "trigger" for call in calls)
        if args[0] == "trigger" and trigger_count == 1:
            return _result(
                4,
                stderr=(
                    "error (workflow_dispatch_ambiguous): response was lost"
                ),
            )
        return _result(0, "4455\n")

    with mock.patch.object(
        workflow, "_check_ci_gate", return_value=(True, ""),
    ), mock.patch.object(
        workflow, "_run_cmd", return_value=_result(0, "abc123\n"),
    ), mock.patch.object(
        workflow, "_github_actions", side_effect=_github_actions,
    ), mock.patch.object(
        workflow, "_poll_github_actions", return_value=(0, "success"),
    ), mock.patch.object(retry.time, "sleep"):
        result = workflow._dispatch_github_actions_workflow(
            {
                "workflow": "publish.yml",
                "inputs": {"source_sha": "{head_sha}"},
                "dispatch_correlation_input": "yoke_dispatch_id",
            },
            name="publish",
            run_id="run-1",
            member_items=[],
            github_repo="upyoke/platform",
            project="yoke",
            project_repo_path="",
            timeout_min=30,
            fresh=False,
            gate_branch="main",
            sd="/tmp/sd",
        )

    assert result == (0, "")
    triggers = [call for call in calls if call[0] == "trigger"]
    assert len(triggers) == 2
    assert triggers[0] == triggers[1]
    request_index = triggers[0].index("--request-id")
    assert triggers[0][request_index + 1] == "deploy:yoke:run-1:publish"


def test_definitive_trigger_failure_is_not_retried() -> None:
    github_actions = mock.Mock(return_value=_result(1, stderr="invalid inputs"))
    result = retry.trigger_with_recovery_retries(
        ("trigger", "o/r", "deploy.yml"),
        github_actions=github_actions,
        project="yoke",
        sd=None,
        timeout_sec=60,
    )
    assert result.returncode == 1
    github_actions.assert_called_once()


def test_definitive_operation_rejection_is_not_retried() -> None:
    github_actions = mock.Mock(return_value=_result(
        4, stderr="error (workflow_dispatch_rejected): HTTP 422",
    ))
    result = retry.trigger_with_recovery_retries(
        ("trigger", "o/r", "deploy.yml"),
        github_actions=github_actions,
        project="yoke",
        sd=None,
        timeout_sec=60,
    )
    assert result.returncode == 4
    github_actions.assert_called_once()
