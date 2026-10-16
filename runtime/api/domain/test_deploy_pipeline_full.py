"""Pipeline stage iteration, branch verification, and CLI parsing."""

from __future__ import annotations

import argparse
import json
import subprocess
from unittest import mock

from yoke_core.domain import (
    deploy_pipeline,
    deploy_pipeline_step_runners,
    deploy_pipeline_reporting,
)


# ===========================================================================
# ===========================================================================


# ===========================================================================
# deploy_pipeline tests
# ===========================================================================


class TestDeployPipeline:
    def test_release_control_plane_uses_active_environment(self, monkeypatch):
        monkeypatch.setenv("YOKE_ENV", "prod-db-admin")

        assert deploy_pipeline._release_control_plane_env() == "prod"

    def test_release_control_plane_reports_unbound_environment(self, monkeypatch):
        monkeypatch.delenv("YOKE_ENV", raising=False)

        assert deploy_pipeline._release_control_plane_env() == "unbound"


class TestDeployPipelineProjectSettings:
    def test_github_actions_subprocess_receives_explicit_project(self, monkeypatch):
        monkeypatch.setenv(
            deploy_pipeline_reporting.GITHUB_ACTIONS_LOCAL_AUTHORITY_ENV,
            "1",
        )
        completed = _fake_cp(0, "success", "")
        with mock.patch.object(
            deploy_pipeline_reporting,
            "_run_cmd",
            return_value=completed,
        ) as run_cmd:
            result = deploy_pipeline_reporting._github_actions(
                "poll",
                "owner/repo",
                "123",
                project="externalwebapp",
            )

        assert result is completed
        command = run_cmd.call_args.args[0]
        assert command[-2:] == ["--project", "externalwebapp"]

    def test_ephemeral_verify_reads_domain_from_ephemeral_policy(self):
        policy = mock.Mock(preview_domain="externalwebapp.example.com")
        with (
            mock.patch(
                "yoke_core.domain.deploy_pipeline_control_plane.ephemeral_qa_ready",
                return_value=False,
            ),
            mock.patch(
                "yoke_core.domain.ephemeral_substrate.load_ephemeral_policy",
                return_value=policy,
            ),
            mock.patch.object(
                deploy_pipeline_step_runners._step_runners,
                "exec_ephemeral_verify",
                return_value=0,
            ) as exec_verify,
        ):
            rc, _diag = deploy_pipeline_step_runners._dispatch_ephemeral_verify(
                {"workflow": "ephemeral.yml"},
                name="verify",
                run_id="run-1",
                github_repo="owner/repo",
                project="externalwebapp",
                project_repo_path="",
                branch="feature",
                first_item="42",
                first_item_label="EXT-42",
                sd="/tmp/sd",
            )

        assert rc == 0
        exec_verify.assert_called_once_with(
            "owner/repo",
            "feature",
            "ephemeral.yml",
            "externalwebapp.example.com",
            "",
            project="externalwebapp",
        )


class TestParseStages:
    def test_basic_parse(self):
        stages_json = json.dumps(
            [
                {"name": "deploy", "step_runner": "auto"},
                {
                    "name": "smoke",
                    "step_runner": "github-actions-workflow",
                    "workflow": "smoke.yml",
                    "dispatch_correlation_input": "yoke_dispatch_id",
                },
            ]
        )
        result = deploy_pipeline._parse_stages(stages_json)
        assert len(result) == 2
        assert result[0]["name"] == "deploy"
        assert result[0]["step_runner"] == "auto"
        assert result[1]["config"]["workflow"] == "smoke.yml"


class TestPipelineCLI:
    def test_cli_parser(self):
        parser = deploy_pipeline._build_parser()
        args = parser.parse_args(
            [
                "run-test-001",
                "--timeout",
                "60",
                "--from-stage",
                "deploy",
                "--fresh",
                "--image-tag",
                "abc123def456",
                "--product-repo-path",
                "/repo",
            ]
        )
        assert args.primary_arg == "run-test-001"
        assert args.timeout == 60
        assert args.from_stage == "deploy"
        assert args.fresh is True
        assert args.image_tag == "abc123def456"
        assert args.product_repo_path == "/repo"

    def test_cli_defaults(self):
        parser = deploy_pipeline._build_parser()
        args = parser.parse_args(["run-test-001"])
        assert args.timeout == 30
        assert args.from_stage == ""
        assert args.fresh is False
        assert args.image_tag == ""
        assert args.product_repo_path == ""

    def test_cli_forwards_explicit_product_repo_path(self, monkeypatch):
        run = mock.Mock(return_value=0)
        monkeypatch.setattr(deploy_pipeline, "run_pipeline", run)

        assert (
            deploy_pipeline.main(
                [
                    "run-test-001",
                    "--product-repo-path",
                    "/pinned",
                ]
            )
            == 0
        )
        assert run.call_args.kwargs["product_repo_path"] == "/pinned"


class TestBackfillCLI:
    def test_dry_run_flag(self):
        parser = argparse.ArgumentParser()
        parser.add_argument("--dry-run", action="store_true")
        args = parser.parse_args(["--dry-run"])
        assert args.dry_run is True


def _fake_cp(
    returncode: int, stdout: str = "", stderr: str = ""
) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(
        args=["gh", "poll"], returncode=returncode, stdout=stdout, stderr=stderr
    )
