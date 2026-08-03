"""CLI contract tests for deployment-flow definition and prose writers."""

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
        result={"flow_id": "yoke-prod", "message": "ok"},
    )


@pytest.fixture(autouse=True)
def _reset_captured() -> None:
    _CAPTURED_REQUESTS.clear()


def _run(*argv: str) -> int:
    with patch.dict("os.environ", {"YOKE_SESSION_ID": "test-session"}):
        with patch(
            "yoke_core.domain.yoke_function_dispatch.dispatch",
            side_effect=_stub_ok,
        ):
            with patch("yoke_cli.commands._helpers.ensure_handlers_loaded"):
                with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                    return cli_main(list(argv))


def test_update_stages_reads_the_advertised_stages_file_flag(tmp_path) -> None:
    """``--stages-file`` is advertised in usage, so it must reach the payload.

    ``add_text_file_pair`` stores the file flag under ``<dest>_file``; reading
    any other attribute raises AttributeError before dispatch and makes the
    documented file round-trip (``deployment-flows get FLOW stages`` into a
    file, then back) unusable.
    """
    stages_file = tmp_path / "stages.json"
    stages_file.write_text('[{"name":"merged","step_runner":"auto"}]')

    rc = _run(
        "deployment-flows", "update-stages", "yoke-prod",
        "--stages-file", str(stages_file),
        "--description", "Deploys the product and its downstream pin.",
    )

    assert rc == 0
    req = _CAPTURED_REQUESTS[-1]
    assert req.function == "deployment_flows.update_stages"
    assert req.payload["stages"] == '[{"name":"merged","step_runner":"auto"}]'
    assert req.payload["description"] == (
        "Deploys the product and its downstream pin."
    )


def test_describe_sends_only_the_description() -> None:
    """Describe must not carry stages, so run history cannot block it."""
    rc = _run(
        "deployment-flows", "describe", "yoke-prod",
        "--description", "Also deploys the downstream repo at pin-branch head.",
    )

    assert rc == 0
    req = _CAPTURED_REQUESTS[-1]
    assert req.function == "deployment_flows.describe"
    assert req.target.kind == "global"
    assert req.payload == {
        "flow_id": "yoke-prod",
        "description": (
            "Also deploys the downstream repo at pin-branch head."
        ),
    }


def test_describe_reads_a_description_file(tmp_path) -> None:
    body = tmp_path / "description.txt"
    body.write_text("Ships the product and its pin in one promotion.")

    rc = _run(
        "deployment-flows", "describe", "yoke-prod",
        "--description-file", str(body),
    )

    assert rc == 0
    assert _CAPTURED_REQUESTS[-1].payload["description"] == (
        "Ships the product and its pin in one promotion."
    )
