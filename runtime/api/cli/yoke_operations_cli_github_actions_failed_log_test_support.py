# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

import io

import json

from contextlib import redirect_stderr, redirect_stdout

from typing import Any, Dict, List

from unittest.mock import patch

import pytest

import yoke_cli.commands.adapters.github_actions_failed_log as failed_log_mod

from yoke_cli.main import main as cli_main

from yoke_cli.transport.https import HttpsConnection

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionCallResponse,
)

_CAPTURED_REQUESTS: List[FunctionCallRequest] = []

_CONNECTION = HttpsConnection(
    api_url="https://control.example",
    token="test-token",
    env="prod",
)


def _run(
    *argv: str,
    result: Dict[str, Any] | None = None,
    error: Dict[str, str] | None = None,
) -> tuple[int, str, str]:
    def relay(
        request: FunctionCallRequest,
        connection: HttpsConnection,
        **_transport_kwargs: object,
    ) -> FunctionCallResponse:
        assert connection == _CONNECTION
        _CAPTURED_REQUESTS.append(request)
        if error is not None:
            return FunctionCallResponse(
                success=False,
                function=request.function,
                version=request.version,
                request_id=request.request_id,
                error=error,
            )
        return FunctionCallResponse(
            success=True,
            function=request.function,
            version=request.version,
            request_id=request.request_id,
            result=dict(result or {}),
        )

    with patch.dict("os.environ", {"YOKE_SESSION_ID": "test-session"}):
        with (
            patch(
                "yoke_cli.commands.adapters.github_actions_workflow.ensure_handlers_loaded"
            ),
            patch(
                "yoke_cli.transport.https.resolve_https_connection",
                return_value=_CONNECTION,
            ),
            patch(
                "yoke_cli.transport.https.relay_https",
                side_effect=relay,
            ),
        ):
            with (
                redirect_stdout(io.StringIO()) as out,
                redirect_stderr(io.StringIO()) as err,
            ):
                rc = cli_main(list(argv))
    return rc, out.getvalue(), err.getvalue()
