# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

import io

import json

from contextlib import redirect_stderr, redirect_stdout
from types import SimpleNamespace

from typing import Any, Dict, List

from unittest.mock import patch

import pytest

from yoke_cli.commands.adapters import github_actions_workflow as workflow_mod

from yoke_cli.main import main as cli_main

from yoke_cli.transport import dispatcher, https
from yoke_cli.transport.https import HttpsConnection, ServerHandshake, TransportError

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
            patch.object(workflow_mod, "ensure_handlers_loaded"),
            patch.object(
                https,
                "active_connection",
                return_value={
                    "transport": "https",
                    "api_url": _CONNECTION.api_url,
                    "env": _CONNECTION.env,
                },
            ),
            patch.object(https, "resolve_token", return_value=_CONNECTION.token),
            patch.object(
                dispatcher,
                "https_transport",
                SimpleNamespace(
                    ServerHandshake=ServerHandshake,
                    TransportError=TransportError,
                    resolve_https_connection=https.resolve_https_connection,
                    relay_https=relay,
                ),
            ),
        ):
            with (
                redirect_stdout(io.StringIO()) as out,
                redirect_stderr(io.StringIO()) as err,
            ):
                rc = cli_main(list(argv))
    return rc, out.getvalue(), err.getvalue()
