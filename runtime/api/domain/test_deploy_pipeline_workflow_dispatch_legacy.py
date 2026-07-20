"""Rollout compatibility for workflows without dispatch correlation."""

from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
import io
import os
import subprocess
from unittest import mock

from yoke_cli.commands.adapters import github_actions_workflow as workflow_adapter
from yoke_cli.main import main as cli_main
from yoke_cli.transport.https import HttpsConnection
from yoke_contracts.api.function_call import FunctionCallResponse
from yoke_core.domain import deploy_pipeline_github_workflow as workflow


def _result(returncode: int, stdout: str = "", stderr: str = ""):
    return subprocess.CompletedProcess([], returncode, stdout, stderr)


def _dispatch(config: dict[str, object], tmp_path) -> tuple[int, str]:
    # A real .git satisfies the checkout-existence preflight; git is mocked.
    checkout = tmp_path / "externalwebapp"
    (checkout / ".git").mkdir(parents=True, exist_ok=True)
    return workflow._dispatch_github_actions_workflow(
        config,
        name="prod-deploy",
        run_id="run-legacy",
        member_items=[],
        github_repo="upyoke/externalwebapp",
        project="externalwebapp",
        project_repo_path=str(checkout),
        timeout_min=30,
        fresh=False,
        gate_branch="main",
        release_lineage="a" * 40,
        sd="/tmp/sd",
    )


def test_legacy_stage_uses_one_shot_dispatch_without_durable_flags(tmp_path) -> None:
    github_actions = mock.Mock(return_value=_result(0, "4455\n"))
    with mock.patch.object(
        workflow, "_check_ci_gate", return_value=(True, ""),
    ), mock.patch.object(
        workflow, "_run_cmd", return_value=_result(0, "abc123\n"),
    ), mock.patch.object(
        workflow, "_find_existing_workflow_run", return_value=("", False, ""),
    ), mock.patch.object(
        workflow, "_github_actions", github_actions,
    ), mock.patch.object(
        workflow, "_poll_github_actions", return_value=(0, "success"),
    ), mock.patch.object(
        workflow, "trigger_with_recovery_retries",
    ) as durable_dispatch:
        result = _dispatch({"workflow": "externalwebapp-deploy.yml"}, tmp_path)

    assert result == (0, "")
    durable_dispatch.assert_not_called()
    assert github_actions.call_args_list == [
        mock.call(
            "trigger-once",
            "upyoke/externalwebapp",
            "externalwebapp-deploy.yml",
            "--ref",
            "main",
            project="externalwebapp",
            sd="/tmp/sd",
        )
    ]


def test_legacy_input_stage_does_not_retry_ambiguous_dispatch(tmp_path) -> None:
    github_actions = mock.Mock(
        return_value=_result(
            4,
            stderr="error (workflow_dispatch_ambiguous): response was lost",
        )
    )
    with mock.patch.object(
        workflow, "_check_ci_gate", return_value=(True, ""),
    ), mock.patch.object(
        workflow, "_run_cmd", return_value=_result(0, "abc123\n"),
    ), mock.patch.object(
        workflow, "_github_actions", github_actions,
    ), mock.patch.object(
        workflow, "trigger_with_recovery_retries",
    ) as durable_dispatch:
        result = _dispatch(
            {
                "workflow": "externalwebapp-deploy.yml",
                "inputs": {"force_rebuild": "false"},
            },
            tmp_path,
        )

    assert result == (
        1,
        "error (workflow_dispatch_ambiguous): response was lost",
    )
    durable_dispatch.assert_not_called()
    assert github_actions.call_count == 1
    trigger_args = github_actions.call_args.args
    assert trigger_args[0] == "trigger-once"
    assert "--request-id" not in trigger_args
    assert "--correlation-input" not in trigger_args


def test_explicit_unsupported_correlation_input_still_fails_closed(tmp_path) -> None:
    ci_gate = mock.Mock(return_value=(True, ""))
    with mock.patch.object(workflow, "_check_ci_gate", ci_gate):
        result = _dispatch(
            {
                "workflow": "externalwebapp-deploy.yml",
                "dispatch_correlation_input": "custom_dispatch_id",
            },
            tmp_path,
        )

    assert result == (
        1,
        "github-actions-workflow stage declares unsupported dispatch correlation input",
    )
    ci_gate.assert_not_called()


def test_legacy_pipeline_reaches_explicit_one_shot_typed_cli(tmp_path) -> None:
    connection = HttpsConnection(
        api_url="https://control.example",
        token="deployment-token",
        env="prod",
    )
    captured = []

    def _relay(request, selected_connection):
        assert selected_connection == connection
        captured.append(request)
        return FunctionCallResponse(
            success=True,
            function=request.function,
            version=request.version,
            result={"run_id": "4455"},
        )

    def _typed_cli(*args, project, sd=None, timeout=60):
        del sd, timeout
        stdout = io.StringIO()
        stderr = io.StringIO()
        with mock.patch.object(
            workflow_adapter, "ensure_handlers_loaded",
        ), mock.patch(
            "yoke_cli.transport.https.resolve_https_connection",
            return_value=connection,
        ), mock.patch(
            "yoke_cli.transport.https.relay_https",
            side_effect=_relay,
        ), mock.patch.dict(
            os.environ,
            {"YOKE_SESSION_ID": "legacy-pipeline-test"},
            clear=False,
        ), redirect_stdout(stdout), redirect_stderr(stderr):
            returncode = cli_main(
                ["github-actions", *args, "--project", project]
            )
        return subprocess.CompletedProcess(
            list(args), returncode, stdout.getvalue(), stderr.getvalue()
        )

    with mock.patch.object(
        workflow, "_check_ci_gate", return_value=(True, ""),
    ), mock.patch.object(
        workflow, "_run_cmd", return_value=_result(0, "abc123\n"),
    ), mock.patch.object(
        workflow, "_find_existing_workflow_run", return_value=("", False, ""),
    ), mock.patch.object(
        workflow, "_github_actions", side_effect=_typed_cli,
    ), mock.patch.object(
        workflow, "_poll_github_actions", return_value=(0, "success"),
    ):
        result = _dispatch({"workflow": "externalwebapp-deploy.yml"}, tmp_path)

    assert result == (0, "")
    assert len(captured) == 1
    assert captured[0].function == "github_actions.workflow.dispatch_once"
    assert captured[0].request_id
    assert "correlation_input" not in captured[0].payload
