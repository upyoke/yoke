"""CLI coverage for lineage-pinned deployment-run retries."""

from __future__ import annotations

import io
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

from yoke_cli.main import main as cli_main
from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionCallResponse,
)


def test_retry_of_dispatches_the_source_run_without_resolving_a_moving_ref():
    captured = []

    def dispatch(request: FunctionCallRequest) -> FunctionCallResponse:
        captured.append(request)
        return FunctionCallResponse(
            success=True,
            function=request.function,
            version=request.version,
            request_id=request.request_id,
            result={"run_id": "run-20260811-002"},
        )

    with (
        patch.dict("os.environ", {"YOKE_SESSION_ID": "test-session"}),
        patch(
            "yoke_cli.commands.adapters.deployment_run_create."
            "https_product_plane_create_error",
            return_value=None,
        ),
        patch(
            "yoke_cli.commands.adapters.deployment_run_create."
            "resolve_commit_lineage",
        ) as resolve_lineage,
        patch(
            "yoke_core.domain.yoke_function_dispatch.dispatch",
            side_effect=dispatch,
        ),
        patch("yoke_cli.commands._helpers.ensure_handlers_loaded"),
    ):
        stdout = io.StringIO()
        stderr = io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            rc = cli_main([
                "deployment-runs", "create", "yoke", "hosted-release",
                "--retry-of", "run-20260810-001",
            ])

    assert rc == 0, stderr.getvalue()
    assert captured[-1].payload == {
        "project": "yoke",
        "flow": "hosted-release",
        "created_by": "operator",
        "retry_of": "run-20260810-001",
    }
    resolve_lineage.assert_not_called()


def test_retry_of_rejects_a_second_lineage_source():
    with patch(
        "yoke_cli.commands.adapters.deployment_run_create."
        "https_product_plane_create_error",
        return_value=None,
    ):
        stderr = io.StringIO()
        with redirect_stderr(stderr):
            rc = cli_main([
                "deployment-runs", "create", "yoke", "hosted-release",
                "--retry-of", "run-20260810-001",
                "--source-ref", "origin/main",
            ])
    assert rc == 2
    assert "cannot be combined" in stderr.getvalue()
