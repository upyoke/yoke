"""CLI coverage for ``yoke github-actions failed-log``."""

from __future__ import annotations

import io
import json
from contextlib import redirect_stderr, redirect_stdout
from typing import Any, Dict, List
from unittest.mock import patch

import pytest

import yoke_cli.commands.adapters.github_actions_failed_log as failed_log_mod
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


@pytest.fixture(autouse=True)
def _reset_captured() -> None:
    _CAPTURED_REQUESTS.clear()


def _run(
    *argv: str,
    result: Dict[str, Any] | None = None,
    error: Dict[str, str] | None = None,
) -> tuple[int, str, str]:
    def relay(
        request: FunctionCallRequest,
        connection: HttpsConnection,
        **_transport_kwargs: object,
    ) -> FunctionCallResponse:
        assert connection == _CONNECTION
        _CAPTURED_REQUESTS.append(request)
        if error is not None:
            return FunctionCallResponse(
                success=False,
                function=request.function,
                version=request.version,
                request_id=request.request_id,
                error=error,
            )
        return FunctionCallResponse(
            success=True,
            function=request.function,
            version=request.version,
            request_id=request.request_id,
            result=dict(result or {}),
        )

    with patch.dict("os.environ", {"YOKE_SESSION_ID": "test-session"}):
        with patch(
            "yoke_cli.commands.adapters.github_actions_workflow.ensure_handlers_loaded"
        ), patch(
            "yoke_cli.transport.https.resolve_https_connection",
            return_value=_CONNECTION,
        ), patch(
            "yoke_cli.transport.https.relay_https",
            side_effect=relay,
        ):
            with redirect_stdout(io.StringIO()) as out, redirect_stderr(
                io.StringIO()
            ) as err:
                rc = cli_main(list(argv))
    return rc, out.getvalue(), err.getvalue()


def test_primary_registry_maps_failed_log() -> None:
    from yoke_cli.commands.registry import SUBCOMMAND_REGISTRY

    assert SUBCOMMAND_REGISTRY[("github-actions", "failed-log")][0] == (
        "github_actions.failed_log"
    )


def test_failed_log_relays_run_id_and_prints_output() -> None:
    rc, out, err = _run(
        "github-actions",
        "failed-log",
        "upyoke/platform",
        "9182736",
        "--project",
        "platform",
        "--tail-lines",
        "25",
        result={
            "run_id": "9182736",
            "output": "failed step output",
            "truncated": False,
        },
    )

    assert rc == 0
    assert out == "failed step output\n"
    assert err == ""
    request = _CAPTURED_REQUESTS[-1]
    assert request.function == "github_actions.failed_log"
    assert request.payload == {
        "repo": "upyoke/platform",
        "project": "platform",
        "tail_lines": 25,
        "run_id": "9182736",
    }


def test_failed_log_resolves_workflow_selector_from_head(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        failed_log_mod,
        "_resolve_head_sha",
        lambda head_ref: (0, "deadbeef" * 5),
    )
    rc, out, err = _run(
        "github-actions",
        "failed-log",
        "upyoke/platform",
        "--workflow",
        "ci.yml",
        "--branch",
        "main",
        "--project",
        "platform",
        result={"run_id": "77", "output": "boom", "truncated": False},
    )

    assert rc == 0
    assert out == "boom\n"
    request = _CAPTURED_REQUESTS[-1]
    assert request.payload == {
        "repo": "upyoke/platform",
        "project": "platform",
        "tail_lines": 50,
        "workflow": "ci.yml",
        "branch": "main",
        "head_sha": "deadbeef" * 5,
    }


def test_failed_log_json_preserves_envelope() -> None:
    rc, out, err = _run(
        "github-actions",
        "failed-log",
        "upyoke/platform",
        "1",
        "--project",
        "platform",
        "--json",
        result={"run_id": "1", "output": "x", "truncated": False},
    )

    assert rc == 0
    assert err == ""
    envelope = json.loads(out)
    assert envelope["function"] == "github_actions.failed_log"
    assert envelope["result"]["output"] == "x"


def test_failed_log_requires_run_id_or_workflow() -> None:
    rc, out, err = _run(
        "github-actions",
        "failed-log",
        "upyoke/platform",
        "--project",
        "platform",
    )

    assert rc == 2
    assert "run id or --workflow is required" in err
