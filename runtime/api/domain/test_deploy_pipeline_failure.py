"""Deploy-stage failure recording and terminal-trace reporting tests."""

from __future__ import annotations

import subprocess
from unittest import mock

from yoke_core.domain import deploy_pipeline, deploy_pipeline_failure


def _completed(
    returncode: int,
    stdout: str = "",
    stderr: str = "",
) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(
        args=[],
        returncode=returncode,
        stdout=stdout,
        stderr=stderr,
    )


def test_failed_stage_reports_terminal_trace_after_recording_state(capsys) -> None:
    traced = []
    emit_event = mock.Mock()
    with (
        mock.patch.object(
            deploy_pipeline_failure.reporting,
            "_set_deploy_stage",
        ) as set_stage,
        mock.patch.object(
            deploy_pipeline_failure.deploy_qa_recorder,
            "cmd_record_stage_result",
        ) as record_qa,
        mock.patch.object(
            deploy_pipeline_failure.reporting,
            "_yoke_db",
        ) as update_run,
        mock.patch.object(
            deploy_pipeline_failure,
            "_report_failure_trace",
            side_effect=lambda run_id: traced.append(run_id),
        ),
    ):
        rc = deploy_pipeline_failure.fail_pipeline_stage(
            exit_code=1,
            diagnostic="failed:failure",
            stage_name="hosted-release",
            run_id="run-20260829-006",
            flow_id="yoke-hosted-prod",
            member_items=["2607"],
            project="yoke",
            sd="/tmp/sd",
            emit_event=emit_event,
        )

    assert rc == deploy_pipeline.EXIT_STAGE_FAILED
    assert emit_event.call_count == 2
    set_stage.assert_called_once()
    record_qa.assert_called_once()
    update_run.assert_called_once_with(
        "runs",
        "update",
        "run-20260829-006",
        "status",
        "failed",
        sd="/tmp/sd",
    )
    assert traced == ["run-20260829-006"]
    assert "stage 'hosted-release' failed" in capsys.readouterr().err


def test_failure_trace_uses_the_owning_https_control_plane(monkeypatch) -> None:
    monkeypatch.setenv("YOKE_ENV", "prod-db-admin")
    monkeypatch.delenv(
        deploy_pipeline_failure.poll_authority.GITHUB_ACTIONS_RELAY_ENV,
        raising=False,
    )
    monkeypatch.delenv(
        deploy_pipeline_failure.poll_authority.GITHUB_ACTIONS_LOCAL_AUTHORITY_ENV,
        raising=False,
    )
    completed = _completed(0, "Terminal failing job: build", "")
    with mock.patch.object(
        deploy_pipeline_failure.reporting,
        "_run_cmd",
        return_value=completed,
    ) as run_cmd:
        result = deploy_pipeline_failure._failure_trace_command("run-1")

    assert result is completed
    command = run_cmd.call_args.args[0]
    assert command[3:5] == ["--env", "prod"]
    assert command[-3:] == ["deployment-runs", "failure-trace", "run-1"]


def test_failure_trace_timeout_returns_a_diagnosed_partial_failure(monkeypatch) -> None:
    monkeypatch.setenv(
        deploy_pipeline_failure.poll_authority.GITHUB_ACTIONS_LOCAL_AUTHORITY_ENV,
        "1",
    )
    monkeypatch.delenv(
        deploy_pipeline_failure.poll_authority.GITHUB_ACTIONS_RELAY_ENV,
        raising=False,
    )
    with mock.patch.object(
        deploy_pipeline_failure.reporting,
        "_run_cmd",
        side_effect=subprocess.TimeoutExpired(cmd=[], timeout=180),
    ):
        result = deploy_pipeline_failure._failure_trace_command("run-1")

    assert result.returncode == 124
    assert "timed out after 180 seconds" in result.stderr
