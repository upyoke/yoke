"""GitHub Actions deploy-stage polling resilience."""

from __future__ import annotations

import subprocess
from unittest import mock

from yoke_core.domain import deploy_pipeline_reporting


def _fake_cp(
    returncode: int,
    stdout: str = "",
    stderr: str = "",
) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(
        args=["gh", "poll"],
        returncode=returncode,
        stdout=stdout,
        stderr=stderr,
    )


class TestPollGithubActionsTransient:
    """Bounded retries preserve queued work while surfacing real failures."""

    def test_transient_unknown_code_recovers_to_success(self):
        responses = [
            _fake_cp(4, "", "gh: transient API error"),
            _fake_cp(0, "completed: success", ""),
        ]
        with mock.patch.object(
            deploy_pipeline_reporting, "_github_actions", side_effect=responses
        ), mock.patch.object(deploy_pipeline_reporting.time, "sleep"):
            code, output = deploy_pipeline_reporting._poll_github_actions(
                "owner/repo", "12345", timeout_sec=300,
                stage_name="prod-deploy", project="externalwebapp",
            )
        assert code == 0
        assert "completed: success" in output

    def test_sustained_unknown_code_eventually_fails_with_diagnostic(self):
        responses = [
            _fake_cp(7, "", "gh: persistent flake")
            for _ in range(deploy_pipeline_reporting.POLL_TRANSIENT_RETRY_LIMIT)
        ]
        with mock.patch.object(
            deploy_pipeline_reporting, "_github_actions", side_effect=responses
        ), mock.patch.object(deploy_pipeline_reporting.time, "sleep"):
            code, output = deploy_pipeline_reporting._poll_github_actions(
                "owner/repo", "12345", timeout_sec=300,
                stage_name="prod-deploy", project="externalwebapp",
            )
        assert code == 1
        assert "unexpected exit code 7" in output
        assert "gh: persistent flake" in output
        assert "retries" in output

    def test_real_failure_includes_stderr_for_diagnostics(self):
        responses = [
            _fake_cp(
                1,
                "completed: failure",
                "step `deploy` failed: container exited 137",
            ),
        ]
        with mock.patch.object(
            deploy_pipeline_reporting, "_github_actions", side_effect=responses
        ):
            code, output = deploy_pipeline_reporting._poll_github_actions(
                "owner/repo", "12345", timeout_sec=300,
                stage_name="prod-deploy", project="externalwebapp",
            )
        assert code == 1
        assert "completed: failure" in output
        assert "container exited 137" in output

    def test_queued_state_keeps_polling_then_succeeds(self):
        responses = [
            _fake_cp(2, "queued", ""),
            _fake_cp(3, "in_progress", ""),
            _fake_cp(0, "completed: success", ""),
        ]
        with mock.patch.object(
            deploy_pipeline_reporting, "_github_actions", side_effect=responses
        ), mock.patch.object(deploy_pipeline_reporting.time, "sleep"):
            code, output = deploy_pipeline_reporting._poll_github_actions(
                "owner/repo", "12345", timeout_sec=300,
                stage_name="prod-deploy", project="externalwebapp",
            )
        assert code == 0
        assert "completed: success" in output
