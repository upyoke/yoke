"""CLI routing for deployment-run membership operations."""

from __future__ import annotations

import io
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

from yoke_cli.main import main as cli_main
from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionCallResponse,
)


CAPTURED: list[FunctionCallRequest] = []


def _dispatch(request: FunctionCallRequest) -> FunctionCallResponse:
    CAPTURED.append(request)
    result = {
        "run_id": "run-20260909-001",
        "item_id": 3165,
        "valid": True,
        "message": "OK",
    }
    return FunctionCallResponse(
        success=True,
        function=request.function,
        version=request.version,
        request_id=request.request_id,
        result=result,
    )


def _run(*argv: str) -> tuple[int, str, str]:
    CAPTURED.clear()
    with (
        patch.dict("os.environ", {"YOKE_SESSION_ID": "test-session"}),
        patch(
            "yoke_core.domain.yoke_function_dispatch.dispatch",
            side_effect=_dispatch,
        ),
        patch("yoke_cli.commands._helpers.ensure_handlers_loaded"),
    ):
        stdout = io.StringIO()
        stderr = io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            result = cli_main(list(argv))
    return result, stdout.getvalue(), stderr.getvalue()


def test_registry_exposes_membership_commands() -> None:
    from yoke_cli.commands.registry import SUBCOMMAND_REGISTRY

    assert SUBCOMMAND_REGISTRY[("deployment-runs", "add-item")][0] == (
        "deployment_runs.add_item"
    )
    assert SUBCOMMAND_REGISTRY[
        ("deployment-runs", "validate-composition")
    ][0] == "deployment_runs.validate_composition"


def test_add_item_routes_public_ref_for_server_side_resolution() -> None:
    rc, out, err = _run(
        "deployment-runs",
        "add-item",
        "run-20260909-001",
        "YOK-3048",
    )

    assert rc == 0, err
    assert out == "OK\n"
    request = CAPTURED[-1]
    assert request.function == "deployment_runs.add_item"
    assert request.target.kind == "item"
    assert request.target.public_ref == "YOK-3048"
    assert request.target.item_id is None
    assert request.payload == {"run_id": "run-20260909-001"}


def test_add_item_preserves_project_hint_for_bare_item_ref() -> None:
    rc, _out, err = _run(
        "deployment-runs",
        "add-item",
        "run-20260909-001",
        "3048",
        "--project",
        "yoke",
    )

    assert rc == 0, err
    request = CAPTURED[-1]
    assert request.target.public_ref == "3048"
    assert request.target.project_id == "yoke"


def test_validate_composition_routes_run_target() -> None:
    rc, out, err = _run(
        "deployment-runs",
        "validate-composition",
        "run-20260909-001",
    )

    assert rc == 0, err
    assert out == "OK\n"
    request = CAPTURED[-1]
    assert request.function == "deployment_runs.validate_composition"
    assert request.target.kind == "workflow_run"
    assert request.target.workflow_run_id == "run-20260909-001"
    assert request.payload == {}
