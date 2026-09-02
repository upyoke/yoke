"""GitHub Actions deploy-stage polling resilience."""

from __future__ import annotations

import subprocess
from unittest import mock

from yoke_core.domain import deploy_pipeline_poll_authority as poll_authority
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
    """The stage budget survives relay outages while real errors stay bounded."""

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
                project="externalwebapp",
            )
        assert code == 0
        assert "completed: success" in output

    def test_sustained_unknown_code_eventually_fails_with_diagnostic(self):
        responses = [
            _fake_cp(7, "", "gh: persistent flake")
            for _ in range(
                deploy_pipeline_reporting.POLL_UNCLASSIFIED_RETRY_LIMIT
            )
        ]
        with mock.patch.object(
            deploy_pipeline_reporting, "_github_actions", side_effect=responses
        ), mock.patch.object(deploy_pipeline_reporting.time, "sleep"):
            code, output = deploy_pipeline_reporting._poll_github_actions(
                "owner/repo", "12345", timeout_sec=300,
                project="externalwebapp",
            )
        assert code == 1
        assert "unexpected exit code 7" in output
        assert "gh: persistent flake" in output
        assert "retries" in output

    def test_hosted_relay_outage_can_exceed_the_old_short_retry_window(self):
        responses = [
            *[_fake_cp(4, "", "relay unavailable") for _ in range(10)],
            _fake_cp(0, "completed: success", ""),
        ]
        with mock.patch.object(
            deploy_pipeline_reporting, "_github_actions", side_effect=responses
        ), mock.patch.object(
            deploy_pipeline_reporting.time, "time", return_value=100.0
        ), mock.patch.object(deploy_pipeline_reporting.time, "sleep"):
            code, output = deploy_pipeline_reporting._poll_github_actions(
                "owner/repo", "12345", timeout_sec=300,
                project="externalwebapp",
            )
        assert code == 0
        assert "completed: success" in output

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
                project="externalwebapp",
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
                project="externalwebapp",
            )
        assert code == 0
        assert "completed: success" in output


class TestUnansweredStatusRead:
    """A read that hung says nothing about the workflow it was asking about."""

    def test_a_command_that_outlives_its_timeout_is_a_transport_failure(self):
        def _hang(*_args, **_kwargs):
            raise subprocess.TimeoutExpired(cmd="yoke", timeout=60)

        with mock.patch.object(
            deploy_pipeline_reporting.subprocess, "run", side_effect=_hang
        ):
            result = deploy_pipeline_reporting._run_cmd(
                ["yoke", "github-actions", "poll"], timeout=60
            )

        assert result.returncode == poll_authority.TRANSPORT_FAILURE_RETURNCODE
        assert "did not answer within 60s" in result.stderr

    def test_poll_retries_an_unanswered_read_instead_of_abandoning_the_run(self):
        responses = [
            poll_authority.timed_out_result(["yoke", "github-actions", "poll"], 60),
            _fake_cp(0, "completed: success", ""),
        ]
        with mock.patch.object(
            deploy_pipeline_reporting, "_github_actions", side_effect=responses
        ), mock.patch.object(deploy_pipeline_reporting.time, "sleep"):
            code, output = deploy_pipeline_reporting._poll_github_actions(
                "owner/repo", "12345", timeout_sec=300,
                project="externalwebapp",
            )

        assert code == 0
        assert "completed: success" in output
