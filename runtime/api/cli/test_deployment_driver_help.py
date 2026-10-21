"""Deployment driver help, dispatch and selected authority."""

from __future__ import annotations

import sys
from unittest.mock import patch


from runtime.api.cli.test_yoke_operations_cli_deployment import _run_capture, _stub_ok


def test_deployment_run_execute_is_a_client_local_tool() -> None:
    from yoke_cli.commands.tool_shaped import resolve_tool_shaped

    resolved = resolve_tool_shaped(
        [
            "deployment-runs",
            "execute",
            "run-20260616-009",
            "--timeout",
            "90",
        ]
    )
    assert resolved is not None
    adapter, remaining = resolved
    assert adapter.__name__ == "deployment_runs_execute"
    assert remaining == ["run-20260616-009", "--timeout", "90"]


def test_deployment_run_execute_allows_the_selected_external_control_plane() -> None:
    with (
        patch(
            "yoke_cli.commands.deployment_execute.execution_connection_error",
            return_value=None,
        ),
        patch(
            "yoke_cli.commands.deployment_execute.subprocess.run",
        ) as pipeline,
    ):
        pipeline.return_value.returncode = 0
        rc, _out, err = _run_capture(
            _stub_ok,
            "deployment-runs",
            "execute",
            "run-20260616-009",
        )
    assert rc == 0, err
    pipeline.assert_called_once()


def test_deployment_run_execute_help_does_not_require_admin_env() -> None:
    rc, out, err = _run_capture(
        _stub_ok,
        "deployment-runs",
        "execute",
        "--help",
    )
    assert rc == 0
    assert out.startswith("usage: yoke --env CONTROL-PLANE-ENV")
    assert "CONTROL-PLANE-ENV-db-admin" not in out
    assert "--environment" in out
    assert err == ""


def test_deployment_run_execute_calls_pipeline_with_selected_admin_env() -> None:
    with patch(
        "yoke_cli.commands.deployment_execute.subprocess.run",
    ) as pipeline:
        pipeline.return_value.returncode = 0
        rc, _out, err = _run_capture(
            _stub_ok,
            "--env",
            "prod-db-admin",
            "deployment-runs",
            "execute",
            "run-20260616-009",
            "--from-stage",
            "hosted-release",
        )

    assert rc == 0, err
    pipeline.assert_called_once_with(
        [
            sys.executable,
            "-m",
            "yoke_core.domain.deploy_pipeline_liveness_cli",
            "run-20260616-009",
            "--from-stage",
            "hosted-release",
        ],
        check=False,
    )
