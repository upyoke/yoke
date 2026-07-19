"""Dispatch-path tests for ephemeral environment yoke CLI wrappers."""

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
)


_CAPTURED_REQUESTS: List[FunctionCallRequest] = []


@pytest.fixture(autouse=True)
def _reset_captured() -> None:
    _CAPTURED_REQUESTS.clear()


def _run_capture(stub, *argv: str) -> tuple[int, str, str]:
    with patch.dict("os.environ", {"YOKE_SESSION_ID": "test-session"}):
        with patch(
            "yoke_core.domain.yoke_function_dispatch.dispatch",
            side_effect=stub,
        ):
            with patch("yoke_cli.commands._helpers.ensure_handlers_loaded"):
                out = io.StringIO()
                err = io.StringIO()
                with redirect_stdout(out), redirect_stderr(err):
                    rc = cli_main(list(argv))
                return rc, out.getvalue(), err.getvalue()


def test_registry_maps_ephemeral_env_update_to_function_id() -> None:
    from yoke_cli.commands.registry import SUBCOMMAND_REGISTRY

    assert SUBCOMMAND_REGISTRY[("ephemeral-env", "update")][0] == (
        "ephemeral_env.update"
    )


def test_ephemeral_env_get_dispatches_project_branch_and_prints_environment() -> None:
    def stub(request: FunctionCallRequest) -> FunctionCallResponse:
        _CAPTURED_REQUESTS.append(request)
        return FunctionCallResponse(
            success=True,
            function=request.function,
            version=request.version,
            request_id=request.request_id,
            result={
                "environment": {
                    "project": "demo",
                    "branch": "feature-one",
                    "status": "healthy",
                    "url": "https://feature-one.preview.example.com",
                }
            },
        )

    rc, out, _err = _run_capture(
        stub,
        "ephemeral-env",
        "get",
        "demo",
        "feature-one",
    )

    assert rc == 0
    assert '"status": "healthy"' in out
    req = _CAPTURED_REQUESTS[-1]
    assert req.function == "ephemeral_env.get"
    assert req.target.kind == "global"
    assert req.payload == {"project": "demo", "branch": "feature-one"}


def test_ephemeral_env_update_dispatches_global_target_and_prints_message() -> None:
    def stub(request: FunctionCallRequest) -> FunctionCallResponse:
        _CAPTURED_REQUESTS.append(request)
        return FunctionCallResponse(
            success=True,
            function=request.function,
            version=request.version,
            request_id=request.request_id,
            result={
                "env_id": 12,
                "field": "status",
                "value": "healthy",
                "message": "Updated env 12: status=healthy",
                "updated": True,
            },
        )

    rc, out, _err = _run_capture(
        stub,
        "ephemeral-env",
        "update",
        "12",
        "status",
        "healthy",
    )

    assert rc == 0
    assert out == "Updated env 12: status=healthy\n"
    req = _CAPTURED_REQUESTS[-1]
    assert req.function == "ephemeral_env.update"
    assert req.target.kind == "global"
    assert req.payload == {
        "env_id": "12",
        "field": "status",
        "value": "healthy",
    }
