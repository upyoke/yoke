"""Branch resolution and merged-branch deployment gate tests."""

from __future__ import annotations

import subprocess
from unittest import mock

from yoke_core.domain import deploy_pipeline_gates


class TestBranchVerification:
    def test_no_branch(self):
        ok, msg = deploy_pipeline_gates._verify_branch_merged(
            "",
            "42",
            "/tmp/nonexistent",
            "main",
        )
        assert ok is True
        assert "no branch set" in msg
        assert "main" in msg

    def test_null_branch_message_names_target_branch(self):
        ok, msg = deploy_pipeline_gates._verify_branch_merged(
            "null",
            "42",
            "/tmp/nonexistent",
            "stage",
        )
        assert ok is True
        assert "stage" in msg


def _git(repo, *args):
    subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "-c",
            "user.email=t@test",
            "-c",
            "user.name=t",
            *args,
        ],
        check=True,
        capture_output=True,
        text=True,
    )


class TestBranchVerificationDeclaredBranch:
    """The merged gate verifies the flow gate branch, not a fixed branch."""

    def _repo_with_stage_only_work(self, tmp_path):
        repo = tmp_path / "repo"
        repo.mkdir()
        _git(repo, "init", "-b", "main")
        _git(repo, "commit", "--allow-empty", "-m", "root")
        _git(repo, "branch", "stage")
        _git(repo, "checkout", "-b", "wt-stage-only")
        _git(repo, "commit", "--allow-empty", "-m", "stage-only work")
        _git(repo, "checkout", "stage")
        _git(
            repo,
            "merge",
            "--no-ff",
            "-m",
            "land stage-only work",
            "wt-stage-only",
        )
        _git(repo, "checkout", "main")
        return repo

    def test_merged_into_stage_passes_stage_gate(self, tmp_path):
        repo = self._repo_with_stage_only_work(tmp_path)
        ok, msg = deploy_pipeline_gates._verify_branch_merged(
            "wt-stage-only",
            "42",
            str(repo),
            "stage",
        )
        assert (ok, msg) == (True, "")

    def test_stage_only_work_blocks_main_gate(self, tmp_path):
        repo = self._repo_with_stage_only_work(tmp_path)
        ok, msg = deploy_pipeline_gates._verify_branch_merged(
            "wt-stage-only",
            "42",
            str(repo),
            "main",
        )
        assert ok is False
        assert "not on main" in msg


class TestResolveFlowGateBranch:
    """Gate branch = target environment branch, else project base branch."""

    def test_declared_env_branch_wins(self):
        with mock.patch(
            "yoke_core.domain.deploy_environment_settings.declared_env_branch",
            return_value="stage",
        ):
            assert (
                deploy_pipeline_gates.resolve_flow_gate_branch("yoke", "stage")
                == "stage"
            )

    def test_no_target_env_falls_back_to_base_branch(self):
        with mock.patch(
            "yoke_core.domain.project_settings.get_project_str",
            return_value="main",
        ) as get_project_str:
            assert deploy_pipeline_gates.resolve_flow_gate_branch("yoke", "") == "main"
        get_project_str.assert_called_once_with("", "base_branch")

    def test_env_without_declared_branch_falls_back(self):
        with (
            mock.patch(
                "yoke_core.domain.deploy_environment_settings.declared_env_branch",
                return_value="",
            ),
            mock.patch(
                "yoke_core.domain.project_settings.get_project_str",
                return_value="main",
            ),
        ):
            assert (
                deploy_pipeline_gates.resolve_flow_gate_branch(
                    "externalwebapp",
                    "production",
                )
                == "main"
            )

    def test_repo_root_is_passed_to_base_branch_policy_reader(self, tmp_path):
        repo = tmp_path / "checkout"
        with mock.patch(
            "yoke_core.domain.project_settings.get_project_str",
            return_value="trunk",
        ) as get_project_str:
            assert (
                deploy_pipeline_gates.resolve_flow_gate_branch(
                    "externalwebapp",
                    "",
                    str(repo),
                )
                == "trunk"
            )
        get_project_str.assert_called_once_with(str(repo), "base_branch")

    def test_ephemeral_tier_has_no_gate_branch(self):
        """Ephemeral preview flows deploy unmerged branches."""
        assert deploy_pipeline_gates.resolve_flow_gate_branch("yoke", "ephemeral") == ""


class TestEphemeralTierBranchResolution:
    def test_empty_gate_branch_skips_merged_verification(self, capsys):
        with mock.patch.object(
            deploy_pipeline_gates,
            "_active_item_lane_branch",
            return_value="my-branch",
        ):
            ok, first_item, branch = deploy_pipeline_gates._resolve_and_verify_branch(
                ["42"],
                "/repo",
                target_branch="",
                sd=None,
            )
        assert (ok, first_item, branch) == (True, "42", "my-branch")
        assert "Ephemeral tier" in capsys.readouterr().out
