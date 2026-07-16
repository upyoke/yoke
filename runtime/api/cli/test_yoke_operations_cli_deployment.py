"""Dispatch-path tests for deployment flow/run yoke CLI wrappers."""

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


def _stub_ok(request: FunctionCallRequest) -> FunctionCallResponse:
    _CAPTURED_REQUESTS.append(request)
    return FunctionCallResponse(
        success=True,
        function=request.function,
        version=request.version,
        request_id=request.request_id,
        result={"ok": True},
    )


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


def test_registry_maps_deployment_tokens_to_function_ids() -> None:
    from yoke_cli.commands.registry import SUBCOMMAND_REGISTRY

    assert SUBCOMMAND_REGISTRY[("deployment-flows", "get")][0] == (
        "deployment_flows.get"
    )
    assert SUBCOMMAND_REGISTRY[("deployment-flows", "stages")][0] == (
        "deployment_flows.stages"
    )
    assert SUBCOMMAND_REGISTRY[("deployment-runs", "get")][0] == (
        "deployment_runs.get"
    )
    assert SUBCOMMAND_REGISTRY[("deployment-runs", "list")][0] == (
        "deployment_runs.list"
    )
    assert SUBCOMMAND_REGISTRY[("deployment-runs", "update")][0] == (
        "deployment_runs.update"
    )
    assert SUBCOMMAND_REGISTRY[
        ("deployment-runs", "resolve-target-env")
    ][0] == "deployment_runs.resolve_target_env"


def test_flow_stages_dispatches_and_prints_raw_stages() -> None:
    def stub(request: FunctionCallRequest) -> FunctionCallResponse:
        _CAPTURED_REQUESTS.append(request)
        return FunctionCallResponse(
            success=True,
            function=request.function,
            version=request.version,
            request_id=request.request_id,
            result={"flow_id": "yoke-prod", "stages": '[{"name":"deploy"}]'},
        )

    rc, out, _err = _run_capture(
        stub, "deployment-flows", "stages", "yoke-prod",
    )
    assert rc == 0
    assert out == '[{"name":"deploy"}]\n'
    req = _CAPTURED_REQUESTS[-1]
    assert req.function == "deployment_flows.stages"
    assert req.target.kind == "global"
    assert req.payload == {"flow_id": "yoke-prod"}


def test_deployment_run_get_dispatches_workflow_run_target() -> None:
    rc, _out, _err = _run_capture(
        _stub_ok, "deployment-runs", "get", "run-20260616-001", "status",
    )
    assert rc == 0
    req = _CAPTURED_REQUESTS[-1]
    assert req.function == "deployment_runs.get"
    assert req.target.kind == "workflow_run"
    assert req.target.workflow_run_id == "run-20260616-001"
    assert req.payload == {"field": "status"}


def test_deployment_runs_list_prints_pipe_rows() -> None:
    def stub(request: FunctionCallRequest) -> FunctionCallResponse:
        _CAPTURED_REQUESTS.append(request)
        return FunctionCallResponse(
            success=True,
            function=request.function,
            version=request.version,
            request_id=request.request_id,
            result={
                "fields": ["id", "project", "status"],
                "rows": [
                    {
                        "id": "run-20260616-001",
                        "project": "yoke",
                        "status": "created",
                    },
                ],
            },
        )

    rc, out, _err = _run_capture(
        stub, "deployment-runs", "list", "--project", "yoke",
    )
    assert rc == 0
    assert out == "run-20260616-001|yoke|created\n"
    req = _CAPTURED_REQUESTS[-1]
    assert req.function == "deployment_runs.list"
    assert req.payload == {"project": "yoke"}


def test_deployment_run_update_dispatches_and_prints_nothing() -> None:
    rc, out, _err = _run_capture(
        _stub_ok,
        "deployment-runs", "update", "run-20260616-001",
        "status", "succeeded", "--force",
    )
    assert rc == 0
    assert out == ""
    req = _CAPTURED_REQUESTS[-1]
    assert req.function == "deployment_runs.update"
    assert req.target.workflow_run_id == "run-20260616-001"
    assert req.payload == {
        "field": "status",
        "value": "succeeded",
        "force": True,
    }


def test_resolve_target_env_dispatches_and_prints_raw_value() -> None:
    def stub(request: FunctionCallRequest) -> FunctionCallResponse:
        _CAPTURED_REQUESTS.append(request)
        return FunctionCallResponse(
            success=True,
            function=request.function,
            version=request.version,
            request_id=request.request_id,
            result={
                "project": "yoke",
                "flow": "yoke-hosted-production",
                "target_env": "production",
            },
        )

    rc, out, _err = _run_capture(
        stub,
        "deployment-runs", "resolve-target-env",
        "yoke", "yoke-hosted-production",
    )
    assert rc == 0
    assert out == "production\n"
    req = _CAPTURED_REQUESTS[-1]
    assert req.function == "deployment_runs.resolve_target_env"
    assert req.target.kind == "global"
    assert req.payload == {
        "project": "yoke",
        "flow": "yoke-hosted-production",
    }
