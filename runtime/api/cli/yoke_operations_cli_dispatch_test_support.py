# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

import io

from contextlib import redirect_stderr, redirect_stdout

from typing import List

from unittest.mock import patch

import pytest

from yoke_cli.main import main as cli_main

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionCallResponse,
    FunctionError,
)

_CAPTURED_REQUESTS: List[FunctionCallRequest] = []


def _stub_dispatch_ok(request: FunctionCallRequest) -> FunctionCallResponse:
    _CAPTURED_REQUESTS.append(request)
    return FunctionCallResponse(
        success=True,
        function=request.function,
        version=request.version,
        request_id=request.request_id,
        result={
            "echo": True,
            **(
                {
                    "yoke_version": request.payload.get("yoke_version"),
                    "author": request.payload.get("agent"),
                    "universe_fingerprint": "fixture@2026-01-01T00:00:00Z",
                }
                if request.function == "ouroboros.field_note.append"
                else {}
            ),
        },
    )


def _stub_dispatch_fail(request: FunctionCallRequest) -> FunctionCallResponse:
    _CAPTURED_REQUESTS.append(request)
    return FunctionCallResponse(
        success=False,
        function=request.function,
        version=request.version,
        request_id=request.request_id,
        error=FunctionError(code="invalid_payload", message="stub failure"),
    )


@pytest.fixture(autouse=True)
def _reset_captured() -> None:
    _CAPTURED_REQUESTS.clear()


def _run_with_dispatch(stub, *argv: str, session_id: str = "test-session") -> int:
    rc, _out, _err = _run_capture(stub, *argv, session_id=session_id)
    return rc


def _run_capture(
    stub,
    *argv: str,
    session_id: str = "test-session",
) -> tuple[int, str, str]:
    with patch.dict("os.environ", {"YOKE_SESSION_ID": session_id}):
        with (
            patch(
                "yoke_core.domain.yoke_function_dispatch.dispatch",
                side_effect=stub,
            ),
            patch("yoke_cli.commands.adapters.claims.sync_local_snapshot_for_write"),
            patch(
                "yoke_cli.commands.adapters.claims_path_flow.sync_local_snapshot_for_write"
            ),
            patch("yoke_cli.commands._helpers.ensure_handlers_loaded"),
        ):
            buf = io.StringIO()
            err = io.StringIO()
            with redirect_stdout(buf), redirect_stderr(err):
                rc = cli_main(list(argv))
            return rc, buf.getvalue(), err.getvalue()
