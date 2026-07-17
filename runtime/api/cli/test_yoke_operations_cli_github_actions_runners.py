"""CLI tests for ``yoke github-actions runners status``."""

from __future__ import annotations

import io
import json
from contextlib import redirect_stderr, redirect_stdout
from typing import List
from unittest.mock import patch

import pytest

from yoke_cli.main import main as cli_main
from yoke_cli.transport.https import HttpsConnection
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


def _stub_ok(request: FunctionCallRequest) -> FunctionCallResponse:
    _CAPTURED_REQUESTS.append(request)
    return FunctionCallResponse(
        success=True,
        function=request.function,
        version=request.version,
        request_id=request.request_id,
        result={
            "echo": True,
            "ready": False,
            "routing_armed": True,
            "action": "routing_armed_idle",
        },
    )


@pytest.fixture(autouse=True)
def _reset_captured() -> None:
    _CAPTURED_REQUESTS.clear()


def _run(*argv: str) -> tuple[int, str, str]:
    with patch.dict("os.environ", {"YOKE_SESSION_ID": "test-session"}):
        with patch(
            "yoke_core.domain.yoke_function_dispatch.dispatch",
            side_effect=_stub_ok,
        ):
            with patch("yoke_cli.commands._helpers.ensure_handlers_loaded"):
                with redirect_stdout(io.StringIO()) as out, \
                        redirect_stderr(io.StringIO()) as err:
                    rc = cli_main(list(argv))
    return rc, out.getvalue(), err.getvalue()


def test_registry_resolves_runner_status() -> None:
    from yoke_cli.commands.registry import SUBCOMMAND_REGISTRY

    assert SUBCOMMAND_REGISTRY[
        ("github-actions", "runners", "status")
    ][0] == "github_actions.runners.status"


def test_default_runner_status_payload() -> None:
    rc, _out, _err = _run(
        "github-actions", "runners", "status", "upyoke/yoke",
        "--project", "yoke",
    )

    assert rc == 0
    req = _CAPTURED_REQUESTS[-1]
    assert req.function == "github_actions.runners.status"
    assert req.target.kind == "global"
    assert req.payload == {
        "repo": "upyoke/yoke",
        "required_labels": [],
        "variable_name": "",
        "project": "yoke",
        "runner_capability": "github-actions-runner-fleet",
    }


def test_runner_status_uses_https_authority_when_connected() -> None:
    def relay(request, connection):
        assert connection == _CONNECTION
        _CAPTURED_REQUESTS.append(request)
        return FunctionCallResponse(
            success=True,
            function=request.function,
            version=request.version,
            request_id=request.request_id,
            result={"ready": True},
        )

    with patch.dict("os.environ", {"YOKE_SESSION_ID": "test-session"}):
        with patch(
            "yoke_cli.transport.https.resolve_https_connection",
            return_value=_CONNECTION,
        ), patch(
            "yoke_cli.transport.https.relay_https",
            side_effect=relay,
        ):
            with redirect_stdout(io.StringIO()) as out, \
                    redirect_stderr(io.StringIO()) as err:
                rc = cli_main([
                    "github-actions", "runners", "status", "o/r",
                    "--project", "yoke",
                ])

    assert rc == 0
    assert out.getvalue()
    assert err.getvalue() == ""
    assert _CAPTURED_REQUESTS[-1].function == "github_actions.runners.status"


def test_custom_labels_and_project_payload() -> None:
    rc, _out, _err = _run(
        "github-actions", "runners", "status", "o/r",
        "--required-label", "self-hosted",
        "--required-label", "linux",
        "--required-label", "gpu",
        "--variable-name", "CUSTOM_RUNS_ON",
        "--project", "buzz",
    )

    assert rc == 0
    assert _CAPTURED_REQUESTS[-1].payload == {
        "repo": "o/r",
        "required_labels": ["self-hosted", "linux", "gpu"],
        "variable_name": "CUSTOM_RUNS_ON",
        "project": "buzz",
        "runner_capability": "github-actions-runner-fleet",
    }


def test_runner_capability_override_is_not_a_supported_cli_option() -> None:
    rc, _out, err = _run(
        "github-actions", "runners", "status", "o/r",
        "--runner-capability", "custom-runner-fleet",
        "--project", "buzz",
    )

    assert rc == 2
    assert "unrecognized arguments" in err
    assert _CAPTURED_REQUESTS == []


def test_repo_can_be_omitted_for_capability_config() -> None:
    rc, _out, _err = _run(
        "github-actions", "runners", "status",
        "--project", "yoke",
    )

    assert rc == 0
    assert _CAPTURED_REQUESTS[-1].payload == {
        "repo": None,
        "required_labels": [],
        "variable_name": "",
        "project": "yoke",
        "runner_capability": "github-actions-runner-fleet",
    }


def test_repo_without_slash_returns_two() -> None:
    rc, _out, _err = _run(
        "github-actions", "runners", "status", "no-slash",
        "--project", "yoke",
    )

    assert rc == 2
    assert _CAPTURED_REQUESTS == []


def test_json_output_preserves_routing_armed_idle_state() -> None:
    rc, out, err = _run(
        "github-actions", "runners", "status", "upyoke/yoke",
        "--project", "yoke", "--json",
    )

    assert rc == 0
    assert err == ""
    payload = json.loads(out)
    assert payload["result"]["ready"] is False
    assert payload["result"]["routing_armed"] is True
    assert payload["result"]["action"] == "routing_armed_idle"
