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
    assert SUBCOMMAND_REGISTRY[("deployment-runs", "get")][0] == ("deployment_runs.get")
    assert SUBCOMMAND_REGISTRY[("deployment-runs", "approve")][0] == (
        "deployment_runs.approve"
    )
    assert SUBCOMMAND_REGISTRY[("deployment-runs", "list")][0] == (
        "deployment_runs.list"
    )
    assert SUBCOMMAND_REGISTRY[("deployment-runs", "update")][0] == (
        "deployment_runs.update"
    )
    assert (
        SUBCOMMAND_REGISTRY[("deployment-runs", "resolve-target")][0]
        == "deployment_runs.resolve_target"
    )


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
        stub,
        "deployment-flows",
        "stages",
        "yoke-prod",
    )
    assert rc == 0
    assert 'stages: [{"name":"deploy"}]' in out
    req = _CAPTURED_REQUESTS[-1]
    assert req.function == "deployment_flows.stages"
    assert req.target.kind == "global"
    assert req.payload == {"flow_id": "yoke-prod"}


def test_deployment_run_get_dispatches_workflow_run_target() -> None:
    rc, _out, _err = _run_capture(
        _stub_ok,
        "deployment-runs",
        "get",
        "run-20260616-001",
        "status",
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
                "detail_recipe": "yoke deployment-runs get RUN-ID FIELD ...",
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
        stub,
        "deployment-runs",
        "list",
        "--project",
        "yoke",
        "--limit",
        "7",
    )
    assert rc == 0
    assert "id | project | status" in out
    assert "run-20260616-001 | yoke | created" in out
    req = _CAPTURED_REQUESTS[-1]
    assert req.function == "deployment_runs.list"
    assert req.payload == {"summary": True, "project": "yoke", "limit": 7}


def test_deployment_runs_overview_uses_the_shipping_read() -> None:
    rc, _, _ = _run_capture(
        _stub_ok, "deployment-runs", "list", "--relevance", "overview"
    )
    assert rc == 0
    assert _CAPTURED_REQUESTS[-1].function == "deployment_runs.list"
    assert _CAPTURED_REQUESTS[-1].payload == {"relevance": "overview"}


def test_deployment_run_update_dispatches_and_prints_receipt() -> None:
    rc, out, _err = _run_capture(
        _stub_ok,
        "deployment-runs",
        "update",
        "run-20260616-001",
        "status",
        "succeeded",
        "--force",
    )
    assert rc == 0
    assert "ok: yes" in out
    req = _CAPTURED_REQUESTS[-1]
    assert req.function == "deployment_runs.update"
    assert req.target.workflow_run_id == "run-20260616-001"
    assert req.payload == {
        "field": "status",
        "value": "succeeded",
        "force": True,
    }


def test_deployment_run_approve_dispatches_note_and_prints_transition() -> None:
    def stub(request: FunctionCallRequest) -> FunctionCallResponse:
        _CAPTURED_REQUESTS.append(request)
        return FunctionCallResponse(
            success=True,
            function=request.function,
            version=request.version,
            request_id=request.request_id,
            result={
                "run_id": "run-20260616-001",
                "approved_stage": "prod-approval",
                "next_stage": "prod",
            },
        )

    rc, out, err = _run_capture(
        stub,
        "deployment-runs",
        "approve",
        "run-20260616-001",
        "--note",
        "stage verified",
    )
    assert rc == 0, err
    assert out == ("Approved run-20260616-001: prod-approval -> prod\n")
    req = _CAPTURED_REQUESTS[-1]
    assert req.function == "deployment_runs.approve"
    assert req.target.workflow_run_id == "run-20260616-001"
    assert req.payload == {"note": "stage verified"}


def test_resolve_target_dispatches_and_prints_typed_triple() -> None:
    def stub(request: FunctionCallRequest) -> FunctionCallResponse:
        _CAPTURED_REQUESTS.append(request)
        return FunctionCallResponse(
            success=True,
            function=request.function,
            version=request.version,
            request_id=request.request_id,
            result={
                "project": "yoke",
                "flow": "yoke-hosted-prod",
                "target_tier": "persistent",
                "target_environment": "prod",
            },
        )

    rc, out, _err = _run_capture(
        stub,
        "deployment-runs",
        "resolve-target",
        "yoke",
        "yoke-hosted-prod",
    )
    assert rc == 0
    assert "target tier: persistent" in out
    assert "target environment: prod" in out
    req = _CAPTURED_REQUESTS[-1]
    assert req.function == "deployment_runs.resolve_target"
    assert req.target.kind == "global"
    assert req.payload == {
        "project": "yoke",
        "flow": "yoke-hosted-prod",
    }


def test_registry_maps_deployment_run_create() -> None:
    from yoke_cli.commands.registry import SUBCOMMAND_REGISTRY

    assert SUBCOMMAND_REGISTRY[("deployment-runs", "create")][0] == (
        "deployment_runs.create"
    )


def test_deployment_run_create_dispatches_mechanically_bound_lineage() -> None:
    def stub(request: FunctionCallRequest) -> FunctionCallResponse:
        _CAPTURED_REQUESTS.append(request)
        return FunctionCallResponse(
            success=True,
            function=request.function,
            version=request.version,
            request_id=request.request_id,
            result={
                "run_id": "run-20260616-009",
                "project": "yoke",
                "flow": "yoke-hosted-prod",
                "target_tier": "persistent",
                "target_environment": "prod",
                "status": "created",
            },
        )

    with patch(
        "yoke_cli.commands.adapters.deployment_run_create.resolve_commit_lineage",
        return_value="a" * 40,
    ) as resolve_lineage:
        rc, out, err = _run_capture(
            stub,
            "deployment-runs",
            "create",
            "yoke",
            "yoke-hosted-prod",
            "--idempotency-key",
            "prod-release-1",
            "--created-by",
            "operator",
            "--project-repo-path",
            "/repo",
            "--source-ref",
            "origin/main",
        )

    assert rc == 0, err
    assert "run id: run-20260616-009" in out
    request = _CAPTURED_REQUESTS[-1]
    assert request.function == "deployment_runs.create"
    assert request.target.kind == "global"
    assert request.payload == {
        "project": "yoke",
        "flow": "yoke-hosted-prod",
        "created_by": "operator",
        "idempotency_key": "prod-release-1",
        "release_lineage": "a" * 40,
    }
    resolve_lineage.assert_called_once_with("/repo", "origin/main")
