"""CLI dispatch contracts for complete deployment-flow configuration."""

from __future__ import annotations

import io
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

import pytest

from yoke_cli.main import main as cli_main
from yoke_contracts.api.function_call import FunctionCallRequest, FunctionCallResponse


CAPTURED: list[FunctionCallRequest] = []


def _dispatch(request: FunctionCallRequest) -> FunctionCallResponse:
    CAPTURED.append(request)
    return FunctionCallResponse(
        success=True,
        function=request.function,
        version=request.version,
        request_id=request.request_id,
        result={
            "flow_id": "release-v2",
            "flow": {
                "id": "release-v2",
                "definition_schema_version": 2,
                "status": "disabled",
            },
            "valid": True,
            "definition_schema_version": 2,
            "execution_supported": False,
        },
    )


@pytest.fixture(autouse=True)
def _reset() -> None:
    CAPTURED.clear()


def _run(*args: str) -> tuple[int, str, str]:
    stdout = io.StringIO()
    stderr = io.StringIO()
    with patch.dict("os.environ", {"YOKE_SESSION_ID": "configuration-test"}):
        with patch(
            "yoke_core.domain.yoke_function_dispatch.dispatch",
            side_effect=_dispatch,
        ):
            with patch("yoke_cli.commands._helpers.ensure_handlers_loaded"):
                with redirect_stdout(stdout), redirect_stderr(stderr):
                    code = cli_main(list(args))
    return code, stdout.getvalue(), stderr.getvalue()


def test_update_sends_only_explicit_definition_changes() -> None:
    code, _out, error = _run(
        "deployment-flows",
        "update",
        "release-v1",
        "--description",
        "Stage and production",
        "--target-tier",
        "none",
    )
    assert code == 0, error
    assert CAPTURED[-1].function == "deployment_flows.update"
    assert CAPTURED[-1].payload == {
        "flow_id": "release-v1",
        "changes": {
            "description": "Stage and production",
            "target_tier": None,
            "environment": None,
        },
    }


def test_update_sends_authored_delivery_custody() -> None:
    code, _out, error = _run(
        "deployment-flows",
        "update",
        "release-v1",
        "--takes-delivery-custody",
        "false",
    )
    assert code == 0, error
    assert CAPTURED[-1].payload == {
        "flow_id": "release-v1",
        "changes": {"takes_delivery_custody": False},
    }


def test_reorder_preserves_stage_names_as_an_ordered_list() -> None:
    code, _out, error = _run(
        "deployment-flows",
        "reorder",
        "release-v1",
        "--order",
        "stage,item-qa,production",
    )
    assert code == 0, error
    assert CAPTURED[-1].function == "deployment_flows.reorder"
    assert CAPTURED[-1].payload["order"] == ["stage", "item-qa", "production"]


def test_validate_reads_advanced_stage_json_from_stdin() -> None:
    stages = '[{"name":"qa","step_runner":"qa"}]'
    with patch("sys.stdin", io.StringIO(stages)):
        code, out, error = _run(
            "deployment-flows",
            "validate",
            "--project",
            "yoke",
            "--stdin",
        )
    assert code == 0, error
    assert "execution_supported=false" in out
    assert CAPTURED[-1].payload["stages"] == stages


def test_version_names_source_new_identity_and_disabled_status() -> None:
    code, _out, error = _run(
        "deployment-flows",
        "version",
        "release-v1",
        "release-v2",
        "--name",
        "Release v2",
        "--description",
        "Adds scoped QA",
    )
    assert code == 0, error
    request = CAPTURED[-1]
    assert request.function == "deployment_flows.version"
    assert request.payload == {
        "source_flow_id": "release-v1",
        "new_flow_id": "release-v2",
        "name": "Release v2",
        "changes": {"description": "Adds scoped QA"},
        "status": "disabled",
    }
