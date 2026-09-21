"""Exact-commit CI recovery for direct default-branch release commits."""

from __future__ import annotations

import json
import subprocess
from unittest import mock

from runtime.api.domain.deploy_pipeline_gate_test_support import (
    ci_response as _ci_response,
    commit_file as _commit,
)
from yoke_core.domain import deploy_pipeline_ci_recovery
from yoke_core.domain import deploy_pipeline_gates
from yoke_core.domain import deploy_pipeline_github_workflow
from yoke_core.domain.github_actions_commit_runs_read import (
    CommitRunAuthorityError,
)


def test_missing_exact_run_dispatches_declared_workflow_and_rechecks_sha() -> None:
    calls: list[tuple[str, ...]] = []
    states = iter(("no_runs", "passed"))

    def github_actions(*args: str, **_kwargs):
        calls.append(args)
        if args[0] == "check-ci":
            return _ci_response(next(states))
        return subprocess.CompletedProcess(
            args=args,
            returncode=0,
            stdout="ci-run-42\n",
            stderr="",
        )

    with (
        mock.patch.object(
            deploy_pipeline_gates,
            "project_ci_workflow_file",
            return_value="platform-ci.yml",
        ),
        mock.patch.object(
            deploy_pipeline_gates,
            "_github_actions",
            side_effect=github_actions,
        ),
    ):
        passed, message = deploy_pipeline_gates._check_ci_gate(
            "owner/platform",
            "platform",
            30,
            branch="main",
            head_sha="a" * 40,
    )

    assert passed is True
    assert message == "  CI gate: main@aaaaaaaaaaaa CI passed"
    assert [call[0] for call in calls] == ["check-ci", "trigger", "check-ci"]
    trigger = calls[1]
    assert trigger[trigger.index("--ref") + 1] == "main"
    assert trigger[-2:] == ("--correlation-input", "yoke_dispatch_id")
    for check in (calls[0], calls[2]):
        assert check[check.index("--head-sha") + 1] == "a" * 40


def test_dispatch_refusal_names_commit_workflow_and_recovery() -> None:
    def github_actions(*args: str, **_kwargs):
        if args[0] == "check-ci":
            return _ci_response("no_runs")
        return subprocess.CompletedProcess(
            args=args,
            returncode=4,
            stdout="",
            stderr="workflow_dispatch_rejected: workflow has no dispatch input",
        )

    with (
        mock.patch.object(
            deploy_pipeline_gates,
            "project_ci_workflow_file",
            return_value="platform-ci.yml",
        ),
        mock.patch.object(
            deploy_pipeline_gates,
            "_github_actions",
            side_effect=github_actions,
        ),
    ):
        passed, message = deploy_pipeline_gates._check_ci_gate(
            "owner/platform",
            "platform",
            30,
            branch="main",
            head_sha="b" * 40,
        )

    assert passed is False
    assert "b" * 40 in message
    assert "declared workflow platform-ci.yml" in message
    assert "workflow_dispatch_rejected" in message
    assert "yoke_dispatch_id" in message
    assert "Re-run the deployment" in message


def test_pin_commit_deployment_runs_ci_without_manual_dispatch(tmp_path) -> None:
    repo = tmp_path / "platform"
    subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True)
    _commit(repo, "service.py", "print('ready')\n")
    pin_sha = _commit(repo, "yoke-release-pin.txt", "0.1.1+launch.307\n")

    ci_calls: list[tuple[str, ...]] = []
    states = iter(("no_runs", "passed"))

    def ci_actions(*args: str, **_kwargs):
        ci_calls.append(args)
        if args[0] == "check-ci":
            return _ci_response(next(states))
        return subprocess.CompletedProcess(
            args=args,
            returncode=0,
            stdout="ci-run-pin\n",
            stderr="",
        )

    deploy_actions = mock.Mock(
        return_value=subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout="deploy-run\n",
            stderr="",
        )
    )
    with (
        mock.patch.object(
            deploy_pipeline_gates,
            "project_ci_workflow_file",
            return_value="platform-ci.yml",
        ),
        mock.patch.object(
            deploy_pipeline_gates,
            "_github_actions",
            side_effect=ci_actions,
        ),
        mock.patch.object(
            deploy_pipeline_github_workflow,
            "_find_existing_workflow_run",
            return_value=("", False, ""),
        ),
        mock.patch.object(
            deploy_pipeline_github_workflow,
            "_github_actions",
            deploy_actions,
        ),
        mock.patch.object(
            deploy_pipeline_github_workflow,
            "_poll_github_actions",
            return_value=(0, "completed: success"),
        ),
    ):
        result = deploy_pipeline_github_workflow._dispatch_github_actions_workflow(
            {
                "workflow": "platform-deploy.yml",
                "dispatch_correlation_input": "yoke_dispatch_id",
                "reconcile_by_head_sha": False,
            },
            name="platform-deploy",
            run_id="run-pin-test",
            member_items=[],
            github_repo="owner/platform",
            project="platform",
            project_repo_path=str(repo),
            timeout_min=1,
            fresh=False,
            gate_branch="main",
            release_lineage=pin_sha,
            sd=None,
        )

    assert result == (0, "")
    assert [call[0] for call in ci_calls] == ["check-ci", "trigger", "check-ci"]
    assert all(pin_sha in call for call in (ci_calls[0], ci_calls[2]))
    assert deploy_actions.call_args.args[0] == "trigger"


def test_dispatched_run_for_another_tree_does_not_relax_exact_commit_gate() -> None:
    calls = iter((_ci_response("no_runs"), _ci_response("no_runs")))

    def github_actions(*args: str, **_kwargs):
        if args[0] == "trigger":
            return subprocess.CompletedProcess(
                args=args,
                returncode=0,
                stdout="ci-run-moved\n",
                stderr="",
            )
        return next(calls)

    with (
        mock.patch.object(
            deploy_pipeline_gates,
            "project_ci_workflow_file",
            return_value="platform-ci.yml",
        ),
        mock.patch.object(
            deploy_pipeline_gates,
            "_github_actions",
            side_effect=github_actions,
        ),
    ):
        passed, message = deploy_pipeline_gates._check_ci_gate(
            "owner/platform",
            "platform",
            30,
            branch="main",
            head_sha="c" * 40,
        )

    assert passed is False
    assert "ci-run-moved" in message
    assert "c" * 40 in message
    assert "exact release commit" in message


def test_ci_gate_names_cancelled_conclusion_as_no_verdict() -> None:
    response = {
        "success": True,
        "result": {
            "state": "no_verdict",
            "status": "completed",
            "conclusion": "cancelled",
        },
    }
    with (
        mock.patch.object(
            deploy_pipeline_gates,
            "project_ci_workflow_file",
            return_value="ci.yml",
        ),
        mock.patch.object(
            deploy_pipeline_gates,
            "_github_actions",
            return_value=subprocess.CompletedProcess(
                args=[],
                returncode=0,
                stdout=json.dumps(response),
                stderr="",
            ),
        ),
        mock.patch(
            "yoke_core.domain.github_actions_commit_runs_read.matching_runs",
            return_value=[],
        ),
    ):
        passed, message = deploy_pipeline_gates._check_ci_gate(
            "owner/repo",
            "yoke",
            30,
            branch="main",
            head_sha="deadbeef",
        )

    assert passed is False
    assert message
    assert "no verdict for main@deadbeef" in message
    assert "conclusion cancelled" in message
    assert "CI has failed" not in message
    assert "Fix the failing CI" not in message
    assert "Obtain a CI verdict" in message


def test_no_verdict_refusal_names_cancelled_and_is_not_a_failure() -> None:
    message = deploy_pipeline_ci_recovery.no_verdict_ci_message(
        subject="main@2385ab45c2c8",
        conclusion="cancelled",
        sibling_runs=[],
    )

    assert "no verdict for main@2385ab45c2c8" in message
    assert "conclusion cancelled" in message
    assert "not a test failure" in message
    assert "Obtain a CI verdict" in message
    assert "CI has failed" not in message
    assert "Fix the failing CI" not in message


def test_no_verdict_refusal_names_a_same_tree_merge_queue_conclusion() -> None:
    message = deploy_pipeline_ci_recovery.no_verdict_ci_message(
        subject="main@deadbeef",
        conclusion="cancelled",
        sibling_runs=[
            {
                "name": "yoke-ci",
                "event": "merge_group",
                "head_branch": "gh-readonly-queue/main/pr-1425",
                "conclusion": "success",
            }
        ],
    )

    assert "merge-queue run of yoke-ci" in message
    assert "gh-readonly-queue/main/pr-1425" in message
    assert "already concluded success" in message
    assert "does not satisfy this gate" in message


def test_no_verdict_refusal_survives_a_listing_authority_error() -> None:
    def _raise(*_args, **_kwargs):
        raise CommitRunAuthorityError("the Actions read authority refused")

    with mock.patch(
        "yoke_core.domain.github_actions_commit_runs_read.matching_runs",
        side_effect=_raise,
    ):
        message = deploy_pipeline_ci_recovery.no_verdict_ci_message(
            subject="main@deadbeef",
            conclusion="cancelled",
            project="yoke",
            head_sha="d" * 40,
        )

    assert "no verdict for main@deadbeef" in message
    assert "Obtain a CI verdict" in message
    assert "merge-queue" not in message
