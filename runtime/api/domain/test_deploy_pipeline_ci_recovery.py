"""Exact-commit CI gate refusals for release commits without their own run."""

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


def test_missing_exact_run_fails_by_name_and_dispatches_nothing() -> None:
    calls: list[tuple[str, ...]] = []

    def github_actions(*args: str, **_kwargs):
        calls.append(args)
        return _ci_response("no_runs")

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

    assert passed is False
    assert [call[0] for call in calls] == ["check-ci"]
    assert "a" * 40 in message
    assert "declared workflow platform-ci.yml" in message
    assert "dispatches nothing and waives nothing" in message
    assert "yoke deployment-runs create platform <FLOW>" in message
    assert "without --source-ref" in message


def test_untested_pin_commit_stops_before_the_deploy_workflow(tmp_path) -> None:
    repo = tmp_path / "platform"
    subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True)
    _commit(repo, "service.py", "print('ready')\n")
    pin_sha = _commit(repo, "yoke-release-pin.txt", "0.1.1+launch.307\n")
    ci_calls: list[tuple[str, ...]] = []

    def ci_actions(*args: str, **_kwargs):
        ci_calls.append(args)
        return _ci_response("no_runs")

    deploy_actions = mock.Mock()
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
            "_github_actions",
            deploy_actions,
        ),
    ):
        code, diagnostic = (
            deploy_pipeline_github_workflow._dispatch_github_actions_workflow(
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
        )

    assert code == 1
    assert pin_sha in diagnostic
    assert [call[0] for call in ci_calls] == ["check-ci"]
    deploy_actions.assert_not_called()


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
