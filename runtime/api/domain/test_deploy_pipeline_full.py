"""Pure-unit tests for deploy_pipeline and deploy_qa_recorder.

Covers stage iteration, branch verification, and CLI parsing without a DB.
DB-backed integration tests (deploy_db fixture, seed helpers) live in the
sibling test_deploy_pipeline_qa_integration.py.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from unittest import mock

from yoke_core.domain import (
    deploy_pipeline,
    deploy_pipeline_executors,
    deploy_pipeline_reporting,
    deploy_qa_recorder,
)


# ===========================================================================
# deploy_qa_recorder tests
# ===========================================================================


class TestParseStagesQa:
    """Unit tests for stage QA parsing."""

    def test_explicit_qa_kind(self):
        stages = json.dumps([
            {"name": "deploy", "executor": "auto"},
            {"name": "verify", "executor": "auto", "qa_kind": "health_check"},
        ])
        result = deploy_qa_recorder._parse_stages_qa(stages)
        assert len(result) == 1
        assert result[0]["qa_kind"] == "health_check"
        assert result[0]["name"] == "verify"

    def test_inferred_smoke_kind(self):
        stages = json.dumps([
            {"name": "smoke-test", "executor": "auto"},
        ])
        result = deploy_qa_recorder._parse_stages_qa(stages)
        assert len(result) == 1
        assert result[0]["qa_kind"] == "smoke"

    def test_no_qa_stages(self):
        stages = json.dumps([{"name": "deploy", "executor": "auto"}])
        result = deploy_qa_recorder._parse_stages_qa(stages)
        assert result == []

    def test_custom_success_policy(self):
        stages = json.dumps([
            {"name": "smoke", "executor": "auto", "qa_kind": "smoke",
             "success_policy": "All tests green"},
        ])
        result = deploy_qa_recorder._parse_stages_qa(stages)
        assert result[0]["success_policy"] == "All tests green"

    def test_default_success_policy(self):
        stages = json.dumps([
            {"name": "smoke", "executor": "auto", "qa_kind": "smoke"},
        ])
        result = deploy_qa_recorder._parse_stages_qa(stages)
        assert "conclusion=success" in result[0]["success_policy"]


class TestResolveQaKind:

    def test_explicit_kind_in_config(self):
        stages = json.dumps([{"name": "health", "qa_kind": "health_check"}])
        assert deploy_qa_recorder._resolve_qa_kind_for_stage(stages, "health") == "health_check"

    def test_inferred_smoke_from_name(self):
        stages = json.dumps([{"name": "smoke-test"}])
        assert deploy_qa_recorder._resolve_qa_kind_for_stage(stages, "smoke-test") == "smoke"

    def test_unknown_stage_returns_empty(self):
        stages = json.dumps([{"name": "deploy"}])
        assert deploy_qa_recorder._resolve_qa_kind_for_stage(stages, "deploy") == ""

    def test_fallback_smoke_when_stage_not_in_config(self):
        assert deploy_qa_recorder._resolve_qa_kind_for_stage("[]", "smoke-check") == "smoke"

    def test_invalid_json(self):
        assert deploy_qa_recorder._resolve_qa_kind_for_stage("not-json", "smoke") == "smoke"


# ===========================================================================
# deploy_pipeline tests
# ===========================================================================


class TestDeployPipelineShim:

    def test_executor_helpers_remain_importable_from_deploy_pipeline(self):
        assert deploy_pipeline._dispatch_executor.__module__.endswith("deploy_pipeline_executors")
        assert deploy_pipeline._dispatch_ephemeral_verify.__module__.endswith("deploy_pipeline_executors")
        assert deploy_pipeline._dispatch_github_actions_workflow.__module__.endswith("deploy_pipeline_github_workflow")

    def test_seeded_flow_config_converges_through_seed_stage_repair(self, capsys):
        conn = mock.Mock()
        with mock.patch.object(
            deploy_pipeline, "connect", return_value=conn,
        ), mock.patch.object(
            deploy_pipeline, "ensure_seed_stage",
        ) as ensure_stage:
            deploy_pipeline._converge_seeded_flow_config("yoke-stage-release")

        ensure_stage.assert_called_once_with(
            conn,
            seed_flows=deploy_pipeline._SEED_FLOWS,
            flow_id="yoke-stage-release",
            stage_name="distribution-publish",
            before_stage="complete",
        )
        conn.commit.assert_called_once_with()
        conn.close.assert_called_once_with()
        assert "Seeded deployment flow config converged: yoke-stage-release" in (
            capsys.readouterr().out
        )

    def test_unseeded_flow_config_does_not_repair_seed_stage(self):
        with mock.patch.object(
            deploy_pipeline, "ensure_seed_stage",
        ) as ensure_stage:
            deploy_pipeline._converge_seeded_flow_config("custom-flow")

        ensure_stage.assert_not_called()

    def test_release_control_plane_env_prefers_explicit_label(self, monkeypatch):
        monkeypatch.setenv("YOKE_RELEASE_CONTROL_PLANE_ENV", "stage-db-admin")
        monkeypatch.setenv("YOKE_ENV", "prod-db-admin")
        monkeypatch.setenv("YOKE_PG_DSN", "postgres://example")

        assert deploy_pipeline._release_control_plane_env() == "stage"

    def test_release_control_plane_env_falls_back_to_active_env(self, monkeypatch):
        monkeypatch.delenv("YOKE_RELEASE_CONTROL_PLANE_ENV", raising=False)
        monkeypatch.setenv("YOKE_ENV", "prod-db-admin")

        assert deploy_pipeline._release_control_plane_env() == "prod"

    def test_release_control_plane_env_describes_bare_dsn(self, monkeypatch):
        monkeypatch.delenv("YOKE_RELEASE_CONTROL_PLANE_ENV", raising=False)
        monkeypatch.delenv("YOKE_ENV", raising=False)
        monkeypatch.setenv("YOKE_PG_DSN", "postgres://example")

        assert deploy_pipeline._release_control_plane_env() == "dsn"


class TestDeployPipelineProjectSettings:
    def test_ephemeral_verify_reads_domain_from_ephemeral_policy(self):
        policy = mock.Mock(preview_domain="buzz.example.com")
        with mock.patch.object(
            deploy_pipeline_executors,
            "connect",
            return_value=mock.Mock(close=lambda: None),
        ), mock.patch.object(
            deploy_pipeline_executors,
            "query_scalar",
            return_value=0,
        ), mock.patch(
            "yoke_core.domain.ephemeral_substrate.load_ephemeral_policy",
            return_value=policy,
        ), mock.patch.object(
            deploy_pipeline_executors._executors,
            "exec_ephemeral_verify",
            return_value=0,
        ) as exec_verify:
            rc = deploy_pipeline_executors._dispatch_ephemeral_verify(
                {"workflow": "ephemeral.yml"},
                name="verify",
                run_id="run-1",
                member_items=["42"],
                github_repo="owner/repo",
                project="buzz",
                project_repo_path="",
                branch="feature",
                first_item="42",
                sd="/tmp/sd",
            )

        assert rc == 0
        exec_verify.assert_called_once_with(
            "owner/repo", "feature", "ephemeral.yml", "buzz.example.com", "",
        )


class TestParseStages:

    def test_basic_parse(self):
        stages_json = json.dumps([
            {"name": "deploy", "executor": "auto"},
            {"name": "smoke", "executor": "github-actions-workflow", "workflow": "smoke.yml"},
        ])
        result = deploy_pipeline._parse_stages(stages_json)
        assert len(result) == 2
        assert result[0]["name"] == "deploy"
        assert result[0]["executor"] == "auto"
        assert result[1]["config"]["workflow"] == "smoke.yml"


class TestPipelineCLI:

    def test_cli_parser(self):
        parser = deploy_pipeline._build_parser()
        args = parser.parse_args([
            "run-test-001", "--timeout", "60", "--from-stage", "deploy",
            "--fresh", "--image-tag", "abc123def456",
        ])
        assert args.primary_arg == "run-test-001"
        assert args.timeout == 60
        assert args.from_stage == "deploy"
        assert args.fresh is True
        assert args.image_tag == "abc123def456"

    def test_cli_defaults(self):
        parser = deploy_pipeline._build_parser()
        args = parser.parse_args(["run-test-001"])
        assert args.timeout == 30
        assert args.from_stage == ""
        assert args.fresh is False
        assert args.image_tag == ""


class TestQaRecorderCLI:

    def test_seed_from_flow_parser(self):
        parser = deploy_qa_recorder._build_parser()
        args = parser.parse_args(["seed-from-flow", "run-1"])
        assert args.subcmd == "seed-from-flow"
        assert args.run_id == "run-1"

    def test_record_stage_result_parser(self):
        parser = deploy_qa_recorder._build_parser()
        args = parser.parse_args([
            "record-stage-result", "run-1", "smoke", "pass",
            "--raw-result", '{"key": "val"}',
            "--duration-ms", "1234",
            "--workflow-run", "99",
        ])
        assert args.subcmd == "record-stage-result"
        assert args.verdict == "pass"
        assert args.duration_ms == "1234"
        assert args.workflow_run == "99"

    def test_no_subcmd_returns_2(self):
        assert deploy_qa_recorder.main([]) == 2


class TestBackfillCLI:

    def test_dry_run_flag(self):
        parser = argparse.ArgumentParser()
        parser.add_argument("--dry-run", action="store_true")
        args = parser.parse_args(["--dry-run"])
        assert args.dry_run is True


def _fake_cp(returncode: int, stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(
        args=["gh", "poll"], returncode=returncode, stdout=stdout, stderr=stderr
    )


class TestPollGithubActionsTransient:
    """Bounded-retry on transient/unexpected `gh` poll exit codes.

    A queued GitHub Actions workflow that has not yet acquired a runner is a
    normal cold-start state; a single unexpected returncode from the `gh` CLI
    during that window must not collapse the stage to failed.
    """

    def test_transient_unknown_code_recovers_to_success(self):
        # A single non-{0,1,2,3} returncode followed by success(0) must return
        # success — bounded-retry must absorb the transient flake.
        responses = [
            _fake_cp(4, "", "gh: transient API error"),
            _fake_cp(0, "completed: success", ""),
        ]
        with mock.patch.object(
            deploy_pipeline_reporting, "_github_actions", side_effect=responses
        ), mock.patch.object(deploy_pipeline_reporting.time, "sleep"):
            code, output = deploy_pipeline_reporting._poll_github_actions(
                "owner/repo", "12345", timeout_sec=300, stage_name="prod-deploy"
            )
        assert code == 0
        assert "completed: success" in output

    def test_sustained_unknown_code_eventually_fails_with_diagnostic(self):
        # Exceeding POLL_TRANSIENT_RETRY_LIMIT consecutive unexpected codes
        # surfaces a failure that names the retry count AND the stderr text
        # so the operator can root-cause without log archaeology.
        responses = [
            _fake_cp(7, "", "gh: persistent flake")
            for _ in range(deploy_pipeline_reporting.POLL_TRANSIENT_RETRY_LIMIT)
        ]
        with mock.patch.object(
            deploy_pipeline_reporting, "_github_actions", side_effect=responses
        ), mock.patch.object(deploy_pipeline_reporting.time, "sleep"):
            code, output = deploy_pipeline_reporting._poll_github_actions(
                "owner/repo", "12345", timeout_sec=300, stage_name="prod-deploy"
            )
        assert code == 1
        assert "unexpected exit code 7" in output
        assert "gh: persistent flake" in output
        assert "retries" in output

    def test_real_failure_includes_stderr_for_diagnostics(self):
        # When gh poll reports a real failure (exit 1), the output the caller
        # receives includes both stdout and stderr so the eventual
        # DeploymentRunStageFailed payload can carry root cause.
        responses = [
            _fake_cp(1, "completed: failure", "step `deploy` failed: container exited 137"),
        ]
        with mock.patch.object(
            deploy_pipeline_reporting, "_github_actions", side_effect=responses
        ):
            code, output = deploy_pipeline_reporting._poll_github_actions(
                "owner/repo", "12345", timeout_sec=300, stage_name="prod-deploy"
            )
        assert code == 1
        assert "completed: failure" in output
        assert "container exited 137" in output

    def test_queued_state_keeps_polling_then_succeeds(self):
        # Returncode 2/3 means "queued / in_progress" — keep polling, do not
        # collapse to failure. Guards against a regression that accidentally
        # narrows the queued-state branch.
        responses = [
            _fake_cp(2, "queued", ""),
            _fake_cp(3, "in_progress", ""),
            _fake_cp(0, "completed: success", ""),
        ]
        with mock.patch.object(
            deploy_pipeline_reporting, "_github_actions", side_effect=responses
        ), mock.patch.object(deploy_pipeline_reporting.time, "sleep"):
            code, output = deploy_pipeline_reporting._poll_github_actions(
                "owner/repo", "12345", timeout_sec=300, stage_name="prod-deploy"
            )
        assert code == 0
        assert "completed: success" in output
