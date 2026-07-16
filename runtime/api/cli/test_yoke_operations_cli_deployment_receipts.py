"""CLI dispatch tests for explicit archived deployment receipt reads."""

from __future__ import annotations

import io
import json
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

from yoke_cli.main import main as cli_main
from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionCallResponse,
)


def _run_capture(
    result: dict,
    *argv: str,
) -> tuple[int, str, str, FunctionCallRequest]:
    captured: list[FunctionCallRequest] = []

    def stub(request: FunctionCallRequest) -> FunctionCallResponse:
        captured.append(request)
        return FunctionCallResponse(
            success=True,
            function=request.function,
            version=request.version,
            request_id=request.request_id,
            result=result,
        )

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
    return rc, out.getvalue(), err.getvalue(), captured[-1]


def test_receipt_cli_tokens_are_explicit_archive_surfaces() -> None:
    from yoke_cli.commands.registry import SUBCOMMAND_REGISTRY

    assert SUBCOMMAND_REGISTRY[("deployment-flow-receipts", "get")][0] == (
        "deployment_flow_receipts.get"
    )
    assert SUBCOMMAND_REGISTRY[("deployment-flow-receipts", "list")][0] == (
        "deployment_flow_receipts.list"
    )
    assert SUBCOMMAND_REGISTRY[("deployment-run-receipts", "get")][0] == (
        "deployment_run_receipts.get"
    )
    assert SUBCOMMAND_REGISTRY[("deployment-run-receipts", "list")][0] == (
        "deployment_run_receipts.list"
    )


def test_run_receipt_get_dispatches_global_archive_lookup() -> None:
    receipt = {
        "run_id": "run-archive-001",
        "payload": {"run": {"id": "run-archive-001"}},
        "digest_verified": True,
    }
    rc, out, err, request = _run_capture(
        {"run_id": "run-archive-001", "receipt": receipt},
        "deployment-run-receipts", "get", "run-archive-001",
    )
    assert rc == 0
    assert err == ""
    assert json.loads(out) == receipt
    assert request.function == "deployment_run_receipts.get"
    assert request.target.kind == "global"
    assert request.payload == {"run_id": "run-archive-001"}


def test_flow_receipt_get_dispatches_without_active_flow_target() -> None:
    receipt = {
        "flow_id": "retired-flow",
        "payload": {"flow": {"id": "retired-flow"}},
        "digest_verified": True,
    }
    rc, out, err, request = _run_capture(
        {"flow_id": "retired-flow", "receipt": receipt},
        "deployment-flow-receipts", "get", "retired-flow",
    )
    assert rc == 0
    assert err == ""
    assert json.loads(out) == receipt
    assert request.function == "deployment_flow_receipts.get"
    assert request.target.kind == "global"
    assert request.payload == {"flow_id": "retired-flow"}


def test_run_receipt_list_dispatches_filters_and_prints_summary() -> None:
    fields = ["run_id", "project_slug_snapshot", "flow_id", "status"]
    row = {
        "run_id": "run-archive-001",
        "project_slug_snapshot": "platform",
        "flow_id": "retired-flow",
        "status": "succeeded",
    }
    rc, out, err, request = _run_capture(
        {"fields": fields, "rows": [row]},
        "deployment-run-receipts", "list",
        "--project", "platform", "--flow", "retired-flow",
        "--status", "succeeded",
    )
    assert rc == 0
    assert err == ""
    assert out == "run-archive-001|platform|retired-flow|succeeded\n"
    assert request.function == "deployment_run_receipts.list"
    assert request.target.kind == "global"
    assert request.payload == {
        "project": "platform",
        "flow": "retired-flow",
        "status": "succeeded",
    }
