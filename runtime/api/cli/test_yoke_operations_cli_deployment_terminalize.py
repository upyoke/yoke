"""CLI contract for audited deployment-run terminalization."""

from __future__ import annotations

import io
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

from yoke_cli.main import main as cli_main
from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionCallResponse,
)


def _run(*argv: str):
    captured = []

    def dispatch(request: FunctionCallRequest) -> FunctionCallResponse:
        captured.append(request)
        return FunctionCallResponse(
            success=True,
            function=request.function,
            version=request.version,
            request_id=request.request_id,
            result={
                "run_id": "run-20260804-010",
                "prior_status": "executing",
                "final_status": "cancelled",
            },
        )

    with patch.dict("os.environ", {"YOKE_SESSION_ID": "test-session"}):
        with patch(
            "yoke_core.domain.yoke_function_dispatch.dispatch",
            side_effect=dispatch,
        ):
            with patch("yoke_cli.commands._helpers.ensure_handlers_loaded"):
                stdout = io.StringIO()
                stderr = io.StringIO()
                with redirect_stdout(stdout), redirect_stderr(stderr):
                    rc = cli_main(list(argv))
    return rc, stdout.getvalue(), stderr.getvalue(), captured


def test_terminalize_dispatches_the_audited_function():
    rc, stdout, stderr, captured = _run(
        "deployment-runs",
        "terminalize",
        "run-20260804-010",
        "--disposition",
        "cancelled",
        "--reason",
        "No external workflow remains",
    )
    assert rc == 0, stderr
    assert stdout == (
        "Terminalized run-20260804-010: executing -> cancelled\n"
    )
    request = captured[-1]
    assert request.function == "deployment_runs.terminalize"
    assert request.target.kind == "workflow_run"
    assert request.target.workflow_run_id == "run-20260804-010"
    assert request.payload == {
        "disposition": "cancelled",
        "reason": "No external workflow remains",
    }


def test_terminalize_requires_disposition_and_reason():
    rc, _stdout, stderr, captured = _run(
        "deployment-runs", "terminalize", "run-20260804-010",
    )
    assert rc == 2
    assert "--disposition" in stderr
    assert captured == []


def test_terminalize_is_registered_and_inventoried():
    from yoke_cli.commands.registry import SUBCOMMAND_REGISTRY
    from yoke_cli.operation_inventory import lookup

    assert SUBCOMMAND_REGISTRY[("deployment-runs", "terminalize")][0] == (
        "deployment_runs.terminalize"
    )
    assert lookup("yoke deployment-runs terminalize").status == "wrapped"
