# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

import base64

import io

from contextlib import redirect_stderr, redirect_stdout

from unittest.mock import patch

from yoke_cli.main import main as cli_main

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionCallResponse,
)


def _run(
    *argv: str, stdin: str = "", result: dict | None = None
) -> tuple[int, FunctionCallRequest]:
    captured: list[FunctionCallRequest] = []

    def dispatch(request: FunctionCallRequest) -> FunctionCallResponse:
        captured.append(request)
        return FunctionCallResponse(
            success=True,
            function=request.function,
            request_id=request.request_id,
            version=request.version,
            result=dict(result or {}),
        )

    with (
        patch.dict("os.environ", {"YOKE_SESSION_ID": "qa-catalog-test"}),
        patch(
            "yoke_core.domain.yoke_function_dispatch.dispatch",
            side_effect=dispatch,
        ),
        patch("yoke_cli.commands._helpers.ensure_handlers_loaded"),
        patch("sys.stdin", io.StringIO(stdin)),
        redirect_stdout(io.StringIO()),
        redirect_stderr(io.StringIO()),
    ):
        result = cli_main(list(argv))
    assert captured
    return result, captured[-1]
