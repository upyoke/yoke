"""CLI project-context coverage for ``yoke qa run get``."""

from __future__ import annotations

import io
from contextlib import redirect_stderr, redirect_stdout
from typing import List
from unittest.mock import patch

from yoke_cli.main import main as cli_main
from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionCallResponse,
)


_CAPTURED: List[FunctionCallRequest] = []


def _stub_ok(request: FunctionCallRequest) -> FunctionCallResponse:
    _CAPTURED.append(request)
    return FunctionCallResponse(
        success=True,
        function=request.function,
        version=request.version,
        request_id=request.request_id,
        result={"echo": True},
    )


def _run(*argv: str) -> int:
    _CAPTURED.clear()
    with patch.dict("os.environ", {"YOKE_SESSION_ID": "test-session"}):
        with patch(
            "yoke_core.domain.yoke_function_dispatch.dispatch",
            side_effect=_stub_ok,
        ):
            with patch("yoke_cli.commands._helpers.ensure_handlers_loaded"):
                with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                    return cli_main(list(argv))


def test_dispatches_explicit_project() -> None:
    rc = _run("qa", "run", "get", "--run-id", "8142", "--project", "yoke")
    assert rc == 0
    req = _CAPTURED[-1]
    assert req.function == "qa.run.get"
    assert req.target.kind == "global"
    assert req.target.project_id == "yoke"
    assert req.payload == {"run_id": 8142, "project": "yoke"}


def test_infers_checkout_project_when_flag_omitted() -> None:
    with patch(
        "yoke_cli.commands.adapters.qa_read.client_project_context",
        return_value="yoke",
    ):
        rc = _run("qa", "run", "get", "--run-id", "11873")
    assert rc == 0
    req = _CAPTURED[-1]
    assert req.target.project_id == "yoke"
    assert req.payload == {"run_id": 11873, "project": "yoke"}


def test_missing_project_context_returns_usage_error() -> None:
    with patch(
        "yoke_cli.commands.adapters.qa_read.client_project_context",
        return_value=None,
    ):
        rc = _run("qa", "run", "get", "--run-id", "11873")
    assert rc == 2
    assert _CAPTURED == []


def test_missing_run_id_returns_two() -> None:
    rc = _run("qa", "run", "get", "--project", "yoke")
    assert rc == 2
    assert _CAPTURED == []
