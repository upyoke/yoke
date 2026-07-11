"""Input-bearing GitHub Actions workflow dispatch behavior."""

from __future__ import annotations

import subprocess
from unittest import mock

from yoke_core.domain import deploy_pipeline_github_workflow


class TestInputBearingWorkflowDispatch:
    def test_input_bearing_stage_dispatches_instead_of_sha_only_reconcile(self):
        gh_calls = []

        def _fake_gh(*args, **kwargs):
            gh_calls.append(args)
            if args and args[0] == "trigger":
                return subprocess.CompletedProcess(
                    args=args, returncode=0, stdout="new-run-id\n",
                )
            return subprocess.CompletedProcess(args=args, returncode=0, stdout="")

        with mock.patch.object(
            deploy_pipeline_github_workflow, "_check_ci_gate", return_value=(True, ""),
        ), mock.patch.object(
            deploy_pipeline_github_workflow, "_run_cmd",
            return_value=subprocess.CompletedProcess(
                args=[], returncode=0, stdout="abc1234\n",
            ),
        ), mock.patch.object(
            deploy_pipeline_github_workflow, "_find_existing_workflow_run",
            return_value=("wrong-stage-run-id", True),
        ) as find_existing, mock.patch.object(
            deploy_pipeline_github_workflow, "_github_actions", side_effect=_fake_gh,
        ), mock.patch.object(
            deploy_pipeline_github_workflow, "_poll_github_actions",
            return_value=(0, "completed: success"),
        ), mock.patch.object(
            deploy_pipeline_github_workflow, "_emit_run_event",
        ):
            rc, diag = deploy_pipeline_github_workflow._dispatch_github_actions_workflow(
                {
                    "workflow": "yoke-distribution-publish.yml",
                    "dispatch_correlation_input": "yoke_dispatch_id",
                    "inputs": {
                        "channel": "stable",
                        "target_env": "prod",
                        "source_sha": "{head_sha}",
                    },
                    "ref": "main",
                },
                name="distribution-publish",
                run_id="run-test",
                member_items=[],
                github_repo="owner/repo",
                project="yoke",
                project_repo_path="",
                timeout_min=30,
                fresh=False,
                gate_branch="main",
                sd="/tmp/sd",
            )

        assert (rc, diag) == (0, "")
        find_existing.assert_not_called()
        trigger_calls = [call for call in gh_calls if call and call[0] == "trigger"]
        assert trigger_calls == [
            (
                "trigger",
                "owner/repo",
                "yoke-distribution-publish.yml",
                "--ref",
                "main",
                "--input",
                "channel=stable",
                "--input",
                "source_sha=abc1234",
                "--input",
                "target_env=prod",
                "--request-id",
                "deploy:yoke:run-test:distribution-publish",
                "--correlation-input",
                "yoke_dispatch_id",
            )
        ]

    def test_reconcile_can_be_explicitly_disabled_for_input_bearing_stage(self):
        gh_calls = []

        def _fake_gh(*args, **kwargs):
            gh_calls.append(args)
            if args and args[0] == "trigger":
                return subprocess.CompletedProcess(
                    args=args, returncode=0, stdout="new-run-id\n",
                )
            return subprocess.CompletedProcess(args=args, returncode=0, stdout="")

        with mock.patch.object(
            deploy_pipeline_github_workflow, "_check_ci_gate", return_value=(True, ""),
        ), mock.patch.object(
            deploy_pipeline_github_workflow, "_run_cmd",
            return_value=subprocess.CompletedProcess(
                args=[], returncode=0, stdout="abc1234\n",
            ),
        ), mock.patch.object(
            deploy_pipeline_github_workflow, "_find_existing_workflow_run",
        ) as find_existing, mock.patch.object(
            deploy_pipeline_github_workflow, "_github_actions", side_effect=_fake_gh,
        ), mock.patch.object(
            deploy_pipeline_github_workflow, "_poll_github_actions",
            return_value=(0, "completed: success"),
        ):
            rc, diag = deploy_pipeline_github_workflow._dispatch_github_actions_workflow(
                {
                    "workflow": "yoke-distribution-publish.yml",
                    "dispatch_correlation_input": "yoke_dispatch_id",
                    "inputs": {
                        "channel": "stable",
                        "target_env": "prod",
                        "source_sha": "{head_sha}",
                    },
                    "ref": "main",
                    "reconcile_by_head_sha": False,
                },
                name="distribution-publish",
                run_id="run-test",
                member_items=[],
                github_repo="owner/repo",
                project="yoke",
                project_repo_path="",
                timeout_min=30,
                fresh=False,
                gate_branch="main",
                sd="/tmp/sd",
            )

        assert (rc, diag) == (0, "")
        find_existing.assert_not_called()
        trigger_calls = [call for call in gh_calls if call and call[0] == "trigger"]
        assert trigger_calls == [
            (
                "trigger",
                "owner/repo",
                "yoke-distribution-publish.yml",
                "--ref",
                "main",
                "--input",
                "channel=stable",
                "--input",
                "source_sha=abc1234",
                "--input",
                "target_env=prod",
                "--request-id",
                "deploy:yoke:run-test:distribution-publish",
                "--correlation-input",
                "yoke_dispatch_id",
            )
        ]

    def test_input_bearing_stage_returns_dispatch_failure_without_sha_fallback(self):
        def _fake_gh(*args, **kwargs):
            if args and args[0] == "find-run":
                return subprocess.CompletedProcess(
                    args=args,
                    returncode=0,
                    stdout="not_found\n",
                    stderr="",
                )
            return subprocess.CompletedProcess(
                args=args,
                returncode=1,
                stdout="",
                stderr="dispatch refused",
            )

        with mock.patch.object(
            deploy_pipeline_github_workflow, "_check_ci_gate", return_value=(True, ""),
        ), mock.patch.object(
            deploy_pipeline_github_workflow, "_run_cmd",
            return_value=subprocess.CompletedProcess(
                args=[], returncode=0, stdout="abc1234\n"
            ),
        ), mock.patch.object(
            deploy_pipeline_github_workflow, "_find_existing_workflow_run",
            return_value=("", False),
        ) as find_existing, mock.patch.object(
            deploy_pipeline_github_workflow, "_github_actions", side_effect=_fake_gh,
        ), mock.patch.object(
            deploy_pipeline_github_workflow.time, "sleep",
        ):
            rc, diag = deploy_pipeline_github_workflow._dispatch_github_actions_workflow(
                {
                    "workflow": "yoke-distribution-publish.yml",
                    "dispatch_correlation_input": "yoke_dispatch_id",
                    "inputs": {"channel": "stable"},
                    "ref": "main",
                },
                name="distribution-publish",
                run_id="run-test",
                member_items=[],
                github_repo="owner/repo",
                project="yoke",
                project_repo_path="",
                timeout_min=30,
                fresh=False,
                gate_branch="main",
                sd="/tmp/sd",
            )

        assert rc == 1
        assert diag == "dispatch refused"
        find_existing.assert_not_called()

    def test_workflow_ref_is_deploy_repo_default_not_product_gate_branch(self):
        gh_calls = []

        def _fake_gh(*args, **kwargs):
            gh_calls.append(args)
            if args and args[0] == "trigger":
                return subprocess.CompletedProcess(
                    args=args, returncode=0, stdout="new-run-id\n",
                )
            return subprocess.CompletedProcess(args=args, returncode=0, stdout="")

        with mock.patch.object(
            deploy_pipeline_github_workflow, "_check_ci_gate", return_value=(True, ""),
        ), mock.patch.object(
            deploy_pipeline_github_workflow, "_run_cmd",
            return_value=subprocess.CompletedProcess(
                args=[], returncode=0, stdout="abc1234\n",
            ),
        ), mock.patch.object(
            deploy_pipeline_github_workflow, "_find_existing_workflow_run",
        ), mock.patch.object(
            deploy_pipeline_github_workflow, "_github_actions", side_effect=_fake_gh,
        ), mock.patch.object(
            deploy_pipeline_github_workflow, "_poll_github_actions",
            return_value=(0, "completed: success"),
        ):
            rc, diag = deploy_pipeline_github_workflow._dispatch_github_actions_workflow(
                {
                    "workflow": "yoke-distribution-publish.yml",
                    "dispatch_correlation_input": "yoke_dispatch_id",
                    "inputs": {
                        "channel": "latest",
                        "target_env": "stage",
                        "source_sha": "{head_sha}",
                    },
                    "reconcile_by_head_sha": False,
                },
                name="distribution-publish",
                run_id="run-test",
                member_items=[],
                github_repo="owner/ops-repo",
                project="yoke",
                project_repo_path="",
                timeout_min=30,
                fresh=False,
                gate_branch="stage",
                sd="/tmp/sd",
            )

        assert (rc, diag) == (0, "")
        trigger_calls = [call for call in gh_calls if call and call[0] == "trigger"]
        assert trigger_calls == [
            (
                "trigger",
                "owner/ops-repo",
                "yoke-distribution-publish.yml",
                "--ref",
                "main",
                "--input",
                "channel=latest",
                "--input",
                "source_sha=abc1234",
                "--input",
                "target_env=stage",
                "--request-id",
                "deploy:yoke:run-test:distribution-publish",
                "--correlation-input",
                "yoke_dispatch_id",
            )
        ]
