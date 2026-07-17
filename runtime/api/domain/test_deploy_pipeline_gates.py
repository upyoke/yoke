"""Tests for deployment-pipeline gates (gate branch, merged gate, CI gate)."""

from __future__ import annotations

import json
import subprocess
from unittest import mock

from yoke_core.domain import deploy_pipeline_gates


class TestCiGate:
    def test_ci_gate_reads_workflow_from_capability(self):
        with mock.patch.object(
            deploy_pipeline_gates,
            "project_ci_workflow_file",
            return_value="ci.yml",
        ), mock.patch.object(
            deploy_pipeline_gates,
            "_github_actions",
            return_value=subprocess.CompletedProcess(
                args=[], returncode=0,
                stdout=json.dumps({
                    "success": True,
                    "result": {"state": "passed"},
                }),
                stderr="",
            ),
        ) as github_actions:
            passed, message = deploy_pipeline_gates._check_ci_gate(
                "owner/repo", "buzz", 30, branch="main", sd="/tmp/sd",
            )

        assert passed is True
        assert message == "  CI gate: main CI passed"
        github_actions.assert_called_once()
        assert github_actions.call_args.args[:3] == (
            "check-ci", "owner/repo", "ci.yml",
        )
        # The gate branch threads into the check-ci invocation.
        branch_flag_idx = github_actions.call_args.args.index("--branch")
        assert github_actions.call_args.args[branch_flag_idx + 1] == "main"
        assert github_actions.call_args.kwargs["project"] == "buzz"

    def test_ci_gate_checks_declared_gate_branch(self):
        with mock.patch.object(
            deploy_pipeline_gates,
            "project_ci_workflow_file",
            return_value="ci.yml",
        ), mock.patch.object(
            deploy_pipeline_gates,
            "_github_actions",
            return_value=subprocess.CompletedProcess(
                args=[], returncode=0,
                stdout=json.dumps({
                    "success": True,
                    "result": {"state": "passed"},
                }),
                stderr="",
            ),
        ) as github_actions:
            passed, message = deploy_pipeline_gates._check_ci_gate(
                "owner/repo", "yoke", 30, branch="stage", sd="/tmp/sd",
            )

        assert passed is True
        assert message == "  CI gate: stage CI passed"
        branch_flag_idx = github_actions.call_args.args.index("--branch")
        assert github_actions.call_args.args[branch_flag_idx + 1] == "stage"
        assert github_actions.call_args.kwargs["project"] == "yoke"

    def test_ci_gate_checks_exact_release_sha(self):
        with mock.patch.object(
            deploy_pipeline_gates,
            "project_ci_workflow_file",
            return_value="ci.yml",
        ), mock.patch.object(
            deploy_pipeline_gates,
            "_github_actions",
            return_value=subprocess.CompletedProcess(
                args=[], returncode=0,
                stdout=json.dumps({
                    "success": True,
                    "result": {"state": "passed"},
                }),
                stderr="",
            ),
        ) as github_actions:
            passed, message = deploy_pipeline_gates._check_ci_gate(
                "owner/repo", "yoke", 30, branch="main",
                head_sha="deadbeef", sd="/tmp/sd",
            )

        assert passed is True
        assert message == "  CI gate: main@deadbeef CI passed"
        sha_flag_idx = github_actions.call_args.args.index("--head-sha")
        assert github_actions.call_args.args[sha_flag_idx + 1] == "deadbeef"
        assert "--wait" in github_actions.call_args.args
        assert "--json" in github_actions.call_args.args

    def test_ci_gate_reads_failed_state_in_successful_adapter_response(self):
        response = {
            "success": True,
            "result": {
                "state": "failed",
                "status": "completed",
                "conclusion": "failure",
            },
        }
        with mock.patch.object(
            deploy_pipeline_gates,
            "project_ci_workflow_file",
            return_value="ci.yml",
        ), mock.patch.object(
            deploy_pipeline_gates,
            "_github_actions",
            return_value=subprocess.CompletedProcess(
                args=[], returncode=0, stdout=json.dumps(response), stderr="",
            ),
        ):
            passed, message = deploy_pipeline_gates._check_ci_gate(
                "owner/repo", "yoke", 30, branch="main",
                head_sha="deadbeef",
            )

        assert passed is False
        assert "main branch CI has failed" in message

    def test_ci_gate_does_not_call_adapter_error_a_test_failure(self):
        response = {
            "success": False,
            "error": {
                "code": "project_auth_error",
                "message": "user authorization unavailable",
            },
            "result": {},
        }
        with mock.patch.object(
            deploy_pipeline_gates,
            "project_ci_workflow_file",
            return_value="ci.yml",
        ), mock.patch.object(
            deploy_pipeline_gates,
            "_github_actions",
            return_value=subprocess.CompletedProcess(
                args=[], returncode=1, stdout=json.dumps(response), stderr="",
            ),
        ):
            passed, message = deploy_pipeline_gates._check_ci_gate(
                "owner/repo", "yoke", 30, branch="main",
                head_sha="deadbeef",
            )

        assert passed is False
        assert "project_auth_error" in message
        assert "not a failing test conclusion" in message

    def test_ci_gate_rejects_non_terminal_state_without_calling_it_failed(self):
        response = {
            "success": True,
            "result": {
                "state": "running",
                "status": "in_progress",
                "run_id": 42,
            },
        }
        with mock.patch.object(
            deploy_pipeline_gates,
            "project_ci_workflow_file",
            return_value="ci.yml",
        ), mock.patch.object(
            deploy_pipeline_gates,
            "_github_actions",
            return_value=subprocess.CompletedProcess(
                args=[], returncode=0, stdout=json.dumps(response), stderr="",
            ),
        ):
            passed, message = deploy_pipeline_gates._check_ci_gate(
                "owner/repo", "yoke", 30, branch="main",
                head_sha="deadbeef",
            )

        assert passed is False
        assert "non-terminal state 'running'" in message
        assert "without treating in-progress CI as a test failure" in message

    def test_ci_gate_blocks_when_exact_release_sha_has_no_run(self):
        with mock.patch.object(
            deploy_pipeline_gates,
            "project_ci_workflow_file",
            return_value="ci.yml",
        ), mock.patch.object(
            deploy_pipeline_gates,
            "_github_actions",
            return_value=subprocess.CompletedProcess(
                args=[], returncode=0,
                stdout=json.dumps({
                    "success": True,
                    "result": {"state": "no_runs"},
                }),
                stderr="",
            ),
        ):
            passed, message = deploy_pipeline_gates._check_ci_gate(
                "owner/repo", "yoke", 30, branch="main",
                head_sha="deadbeef",
            )

        assert passed is False
        assert "no CI run exists for exact release commit deadbeef" in message

    def test_ci_gate_blocks_structured_timeout(self):
        response = {
            "success": True,
            "result": {
                "state": "timeout",
                "status": "in_progress",
                "run_id": 42,
            },
        }
        with mock.patch.object(
            deploy_pipeline_gates,
            "project_ci_workflow_file",
            return_value="ci.yml",
        ), mock.patch.object(
            deploy_pipeline_gates,
            "_github_actions",
            return_value=subprocess.CompletedProcess(
                args=[], returncode=0, stdout=json.dumps(response), stderr="",
            ),
        ):
            passed, message = deploy_pipeline_gates._check_ci_gate(
                "owner/repo", "yoke", 30, branch="main",
                head_sha="deadbeef",
            )

        assert passed is False
        assert "main branch CI timed out (30s)" in message

    def test_ci_gate_blocks_auth_exit(self):
        with mock.patch.object(
            deploy_pipeline_gates,
            "project_ci_workflow_file",
            return_value="ci.yml",
        ), mock.patch.object(
            deploy_pipeline_gates,
            "_github_actions",
            return_value=subprocess.CompletedProcess(
                args=[], returncode=4, stdout="", stderr="missing_app_credentials",
            ),
        ):
            passed, message = deploy_pipeline_gates._check_ci_gate(
                "owner/repo", "buzz", 30, branch="main",
            )

        assert passed is False
        assert "required typed response (exit 4)" in message
        assert "missing_app_credentials" in message

    def test_ci_gate_blocks_success_exit_without_typed_response(self):
        with mock.patch.object(
            deploy_pipeline_gates,
            "project_ci_workflow_file",
            return_value="ci.yml",
        ), mock.patch.object(
            deploy_pipeline_gates,
            "_github_actions",
            return_value=subprocess.CompletedProcess(
                args=[], returncode=0, stdout="passed", stderr="",
            ),
        ):
            passed, message = deploy_pipeline_gates._check_ci_gate(
                "owner/repo", "buzz", 30, branch="main",
            )

        assert passed is False
        assert "omitted its required typed response (exit 0)" in message
        assert "cannot prove a CI conclusion" in message


class TestBranchVerification:

    def test_no_branch(self):
        ok, msg = deploy_pipeline_gates._verify_branch_merged("", "42", "/tmp/nonexistent", "main")
        assert ok is True
        assert "no branch set" in msg
        assert "main" in msg

    def test_null_branch_message_names_target_branch(self):
        ok, msg = deploy_pipeline_gates._verify_branch_merged("null", "42", "/tmp/nonexistent", "stage")
        assert ok is True
        assert "stage" in msg


def _git(repo, *args):
    subprocess.run(
        ["git", "-C", str(repo), "-c", "user.email=t@test", "-c", "user.name=t", *args],
        check=True, capture_output=True, text=True,
    )


class TestBranchVerificationDeclaredBranch:
    """The merged gate verifies against the flow's gate branch, not hardwired main."""

    def _repo_with_stage_only_work(self, tmp_path):
        repo = tmp_path / "repo"
        repo.mkdir()
        _git(repo, "init", "-b", "main")
        _git(repo, "commit", "--allow-empty", "-m", "root")
        _git(repo, "branch", "stage")
        _git(repo, "checkout", "-b", "wt-stage-only")
        _git(repo, "commit", "--allow-empty", "-m", "stage-only work")
        _git(repo, "checkout", "stage")
        _git(repo, "merge", "--no-ff", "-m", "land stage-only work", "wt-stage-only")
        _git(repo, "checkout", "main")
        return repo

    def test_merged_into_stage_passes_stage_gate(self, tmp_path):
        repo = self._repo_with_stage_only_work(tmp_path)
        ok, msg = deploy_pipeline_gates._verify_branch_merged(
            "wt-stage-only", "42", str(repo), "stage"
        )
        assert (ok, msg) == (True, "")

    def test_stage_only_work_blocks_main_gate(self, tmp_path):
        repo = self._repo_with_stage_only_work(tmp_path)
        ok, msg = deploy_pipeline_gates._verify_branch_merged(
            "wt-stage-only", "42", str(repo), "main"
        )
        assert ok is False
        assert "not on main" in msg


class TestResolveFlowGateBranch:
    """Gate branch = target env's declared branch, else project base branch."""

    def test_declared_env_branch_wins(self):
        with mock.patch(
            "yoke_core.domain.deploy_environment_settings.declared_env_branch",
            return_value="stage",
        ):
            assert deploy_pipeline_gates.resolve_flow_gate_branch(
                "yoke", "stage"
            ) == "stage"

    def test_no_target_env_falls_back_to_base_branch(self):
        with mock.patch(
            "yoke_core.domain.project_settings.get_project_str",
            return_value="main",
        ) as get_project_str:
            assert deploy_pipeline_gates.resolve_flow_gate_branch(
                "yoke", ""
            ) == "main"
        get_project_str.assert_called_once_with("", "base_branch")

    def test_env_without_declared_branch_falls_back(self):
        with mock.patch(
            "yoke_core.domain.deploy_environment_settings.declared_env_branch",
            return_value="",
        ), mock.patch(
            "yoke_core.domain.project_settings.get_project_str",
            return_value="main",
        ):
            assert deploy_pipeline_gates.resolve_flow_gate_branch(
                "buzz", "production"
            ) == "main"

    def test_repo_root_is_passed_to_base_branch_policy_reader(self, tmp_path):
        repo = tmp_path / "checkout"
        with mock.patch(
            "yoke_core.domain.project_settings.get_project_str",
            return_value="trunk",
        ) as get_project_str:
            assert deploy_pipeline_gates.resolve_flow_gate_branch(
                "buzz", "", str(repo)
            ) == "trunk"
        get_project_str.assert_called_once_with(str(repo), "base_branch")

    def test_ephemeral_tier_has_no_gate_branch(self):
        """target_env="ephemeral" is the worktree tier: preview flows
        deploy unmerged branches, so no merged/CI gate branch exists."""
        assert deploy_pipeline_gates.resolve_flow_gate_branch(
            "yoke", "ephemeral"
        ) == ""


class TestEphemeralTierBranchResolution:
    def test_empty_gate_branch_skips_merged_verification(self, capsys):
        with mock.patch.object(
            deploy_pipeline_gates, "_yoke_db", return_value="my-branch",
        ):
            ok, first_item, branch = (
                deploy_pipeline_gates._resolve_and_verify_branch(
                    ["42"], "/repo", target_branch="", sd=None,
                )
            )
        assert (ok, first_item, branch) == (True, "42", "my-branch")
        assert "Ephemeral tier" in capsys.readouterr().out
