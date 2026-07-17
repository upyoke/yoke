"""GitHub Actions deploy reporting relay-selection coverage."""

from __future__ import annotations

import subprocess
import sys
from unittest import mock

from yoke_core.domain import deploy_pipeline_reporting


def _completed() -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(
        args=["github-actions", "poll"],
        returncode=0,
        stdout="completed: success",
        stderr="",
    )


def test_explicit_https_relay_overrides_inherited_active_env(monkeypatch):
    monkeypatch.setenv("YOKE_ENV", "prod-db-admin")
    monkeypatch.setenv(
        deploy_pipeline_reporting.GITHUB_ACTIONS_RELAY_ENV,
        "prod",
    )
    completed = _completed()

    with mock.patch(
        "yoke_cli.transport.https.resolve_https_connection",
        return_value=mock.sentinel.https_connection,
    ) as resolve, mock.patch.object(
        deploy_pipeline_reporting,
        "_run_cmd",
        return_value=completed,
    ) as run_cmd:
        result = deploy_pipeline_reporting._github_actions(
            "poll",
            "upyoke/platform",
            "123",
            project="platform",
        )

    assert result is completed
    resolve.assert_called_once_with(explicit_env="prod")
    run_cmd.assert_called_once_with(
        [
            sys.executable,
            "-m",
            "yoke_cli.main",
            "--env",
            "prod",
            "github-actions",
            "poll",
            "upyoke/platform",
            "123",
            "--project",
            "platform",
        ],
        timeout=60,
    )


def test_explicit_non_https_relay_refuses_local_credential_fallback(monkeypatch):
    monkeypatch.setenv("YOKE_ENV", "prod-db-admin")
    monkeypatch.setenv(
        deploy_pipeline_reporting.GITHUB_ACTIONS_RELAY_ENV,
        "prod",
    )

    with mock.patch(
        "yoke_cli.transport.https.resolve_https_connection",
        return_value=None,
    ) as resolve, mock.patch.object(
        deploy_pipeline_reporting,
        "_run_cmd",
    ) as run_cmd:
        result = deploy_pipeline_reporting._github_actions(
            "trigger",
            "upyoke/platform",
            "deploy.yml",
            "main",
            project="platform",
        )

    resolve.assert_called_once_with(explicit_env="prod")
    run_cmd.assert_not_called()
    assert result.returncode == 4
    assert result.stdout == ""
    assert "YOKE_GITHUB_ACTIONS_RELAY_ENV selects 'prod'" in result.stderr
    assert "refusing local GitHub credential fallback" in result.stderr


def test_db_admin_env_derives_its_https_sibling_relay(monkeypatch):
    monkeypatch.setenv("YOKE_ENV", "prod-db-admin")
    monkeypatch.delenv(
        deploy_pipeline_reporting.GITHUB_ACTIONS_RELAY_ENV,
        raising=False,
    )
    with mock.patch(
        "yoke_cli.transport.https.resolve_https_connection",
        return_value=mock.sentinel.https_connection,
    ) as resolve, mock.patch.object(
        deploy_pipeline_reporting,
        "_run_cmd",
        return_value=_completed(),
    ) as run_cmd:
        result = deploy_pipeline_reporting._github_actions(
            "poll",
            "upyoke/platform",
            "123",
            project="platform",
        )

    assert result.returncode == 0
    resolve.assert_called_once_with(explicit_env="prod")
    run_cmd.assert_called_once_with(
        [
            sys.executable,
            "-m",
            "yoke_cli.main",
            "--env",
            "prod",
            "github-actions",
            "poll",
            "upyoke/platform",
            "123",
            "--project",
            "platform",
        ],
        timeout=60,
    )


def test_no_selected_authority_refuses_ambient_https_and_local_fallback(
    monkeypatch,
):
    monkeypatch.delenv("YOKE_ENV", raising=False)
    monkeypatch.delenv(
        deploy_pipeline_reporting.GITHUB_ACTIONS_RELAY_ENV,
        raising=False,
    )
    monkeypatch.delenv(
        deploy_pipeline_reporting.GITHUB_ACTIONS_LOCAL_AUTHORITY_ENV,
        raising=False,
    )
    with mock.patch(
        "yoke_cli.transport.https.resolve_https_connection",
        return_value=mock.sentinel.ambient_https,
    ) as resolve, mock.patch.object(
        deploy_pipeline_reporting,
        "_run_cmd",
    ) as run_cmd:
        result = deploy_pipeline_reporting._github_actions(
            "poll",
            "upyoke/platform",
            "123",
            project="platform",
        )

    assert result.returncode == 4
    assert "no GitHub Actions authority selected" in result.stderr
    resolve.assert_not_called()
    run_cmd.assert_not_called()


def test_explicit_local_authority_uses_direct_command(monkeypatch):
    monkeypatch.setenv("YOKE_ENV", "prod-db-admin")
    monkeypatch.delenv(
        deploy_pipeline_reporting.GITHUB_ACTIONS_RELAY_ENV,
        raising=False,
    )
    monkeypatch.setenv(
        deploy_pipeline_reporting.GITHUB_ACTIONS_LOCAL_AUTHORITY_ENV,
        "1",
    )
    completed = _completed()

    with mock.patch.object(
        deploy_pipeline_reporting,
        "_run_cmd",
        return_value=completed,
    ) as run_cmd:
        result = deploy_pipeline_reporting._github_actions(
            "poll",
            "upyoke/platform",
            "123",
            project="platform",
        )

    assert result is completed
    run_cmd.assert_called_once_with(
        [
            sys.executable,
            "-m",
            "yoke_cli.main",
            "github-actions",
            "poll",
            "upyoke/platform",
            "123",
            "--project",
            "platform",
        ],
        timeout=60,
    )


def test_relay_and_local_authority_together_are_rejected(monkeypatch):
    monkeypatch.setenv(
        deploy_pipeline_reporting.GITHUB_ACTIONS_RELAY_ENV,
        "prod",
    )
    monkeypatch.setenv(
        deploy_pipeline_reporting.GITHUB_ACTIONS_LOCAL_AUTHORITY_ENV,
        "1",
    )

    with mock.patch.object(deploy_pipeline_reporting, "_run_cmd") as run_cmd:
        result = deploy_pipeline_reporting._github_actions(
            "poll", "upyoke/platform", "123", project="platform",
        )

    assert result.returncode == 4
    assert "authority is ambiguous" in result.stderr
    run_cmd.assert_not_called()


def test_poll_retries_hosted_transport_failure_instead_of_failing_workflow():
    responses = [
        subprocess.CompletedProcess(
            args=[], returncode=4, stdout="", stderr="relay unavailable",
        ),
        subprocess.CompletedProcess(
            args=[], returncode=4, stdout="", stderr="relay unavailable",
        ),
        subprocess.CompletedProcess(
            args=[], returncode=0, stdout="success\n", stderr="",
        ),
    ]

    with mock.patch.object(
        deploy_pipeline_reporting,
        "_github_actions",
        side_effect=responses,
    ) as github_actions, mock.patch.object(
        deploy_pipeline_reporting.time,
        "time",
        return_value=100.0,
    ), mock.patch.object(
        deploy_pipeline_reporting.time,
        "sleep",
    ) as sleep:
        rc, output = deploy_pipeline_reporting._poll_github_actions(
            "upyoke/platform",
            "123",
            300,
            "prod-deploy",
            project="platform",
        )

    assert (rc, output) == (0, "success")
    assert github_actions.call_count == 3
    assert sleep.call_count == 2


def test_poll_preserves_real_workflow_failure_as_terminal():
    failed = subprocess.CompletedProcess(
        args=[], returncode=1, stdout="failed:failure", stderr="step failed",
    )

    with mock.patch.object(
        deploy_pipeline_reporting,
        "_github_actions",
        return_value=failed,
    ) as github_actions, mock.patch.object(
        deploy_pipeline_reporting.time,
        "time",
        return_value=100.0,
    ), mock.patch.object(
        deploy_pipeline_reporting.time,
        "sleep",
    ) as sleep:
        rc, output = deploy_pipeline_reporting._poll_github_actions(
            "upyoke/platform",
            "123",
            300,
            "prod-deploy",
            project="platform",
        )

    assert rc == 1
    assert output == "failed:failure\nstep failed"
    github_actions.assert_called_once()
    sleep.assert_not_called()
