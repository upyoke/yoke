"""CLI envelope tests for project environment-settings functions."""

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
            result={"settings_json": '{"pulumi":{"activation_state":"render_only"}}'},
        )

    stdout = io.StringIO()
    stderr = io.StringIO()
    with (
        patch.dict("os.environ", {"YOKE_SESSION_ID": "test-session"}),
        patch(
            "yoke_core.domain.yoke_function_dispatch.dispatch",
            side_effect=dispatch,
        ),
        patch("yoke_cli.commands._helpers.ensure_handlers_loaded"),
        redirect_stdout(stdout),
        redirect_stderr(stderr),
    ):
        rc = cli_main(list(argv))
    return rc, stdout.getvalue(), stderr.getvalue(), captured


def test_get_dispatches_environment_identity():
    rc, out, _err, calls = _run(
        "projects",
        "environment-settings",
        "get",
        "--project",
        "platform",
        "--environment-id",
        "yoke-api-prod",
    )
    assert rc == 0
    assert "render_only" in out
    assert calls[0].function == "projects.environment_settings.get"
    assert calls[0].payload == {
        "project": "platform",
        "environment_id": "yoke-api-prod",
    }


def test_merge_parses_json_values():
    rc, _out, _err, calls = _run(
        "projects",
        "environment-settings",
        "merge",
        "--project",
        "platform",
        "--environment-id",
        "yoke-api-prod",
        "--set",
        "pulumi.activation_state=render_only",
        "--set",
        "servers=[]",
    )
    assert rc == 0
    assert calls[0].function == "projects.environment_settings.merge"
    assert calls[0].payload["assignments"] == {
        "pulumi.activation_state": "render_only",
        "servers": [],
    }
