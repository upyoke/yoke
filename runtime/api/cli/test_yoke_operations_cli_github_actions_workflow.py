"""CLI coverage for GitHub Actions workflow orchestration adapters."""

from __future__ import annotations

import io
import json
from contextlib import redirect_stderr, redirect_stdout
from typing import Any, Dict, List
from unittest.mock import patch

import pytest

from yoke_cli.commands.adapters import github_actions_workflow as workflow_mod
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
        with patch.object(workflow_mod, "ensure_handlers_loaded"), patch(
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


@pytest.mark.parametrize(
    ("tokens", "function_id"),
    [
        (("github-actions", "trigger"), "github_actions.workflow.dispatch"),
        (
            ("github-actions", "trigger-once"),
            "github_actions.workflow.dispatch_once",
        ),
        (("github-actions", "find-run"), "github_actions.workflow.find_run"),
        (("github-actions", "poll"), "github_actions.wait_run"),
        (("github-actions", "jobs-count"), "github_actions.run.jobs_count"),
    ],
)
def test_alias_registry_maps_concise_workflow_commands(
    tokens: tuple[str, ...],
    function_id: str,
) -> None:
    from yoke_cli.commands.registry import SUBCOMMAND_ALIAS_REGISTRY

    assert SUBCOMMAND_ALIAS_REGISTRY[tokens][0] == function_id


@pytest.mark.parametrize(
    ("tokens", "function_id"),
    [
        (
            ("github-actions", "workflow", "dispatch"),
            "github_actions.workflow.dispatch",
        ),
        (
            ("github-actions", "workflow", "dispatch-once"),
            "github_actions.workflow.dispatch_once",
        ),
        (
            ("github-actions", "workflow", "find-run"),
            "github_actions.workflow.find_run",
        ),
        (
            ("github-actions", "run", "jobs-count"),
            "github_actions.run.jobs_count",
        ),
        (("github-actions", "wait-run"), "github_actions.wait_run"),
    ],
)
def test_primary_registry_uses_mechanical_workflow_commands(
    tokens: tuple[str, ...],
    function_id: str,
) -> None:
    from yoke_cli.commands.registry import SUBCOMMAND_REGISTRY

    assert SUBCOMMAND_REGISTRY[tokens][0] == function_id


def test_trigger_relays_inputs_and_prints_exact_run_id() -> None:
    rc, out, err = _run(
        "github-actions",
        "trigger",
        "upyoke/platform",
        "deploy.yml",
        "--ref",
        "stage",
        "--input",
        "environment=stage",
        "--input",
        "source_sha=abc123",
        "--request-id",
        "deploy-1",
        "--correlation-input",
        "yoke_dispatch_id",
        "--project",
        "platform",
        result={"run_id": 90210, "html_url": "https://github.example/run"},
    )

    assert rc == 0
    assert out == "90210\n"
    assert err == ""
    request = _CAPTURED_REQUESTS[-1]
    assert request.function == "github_actions.workflow.dispatch"
    assert request.target.kind == "global"
    assert request.actor.session_id == "test-session"
    assert request.payload == {
        "repo": "upyoke/platform",
        "workflow": "deploy.yml",
        "ref": "stage",
        "inputs": {"environment": "stage", "source_sha": "abc123"},
        "project": "platform",
        "correlation_input": "yoke_dispatch_id",
    }
    assert request.request_id == "deploy-1"


def test_trigger_json_preserves_hosted_response_envelope() -> None:
    rc, out, err = _run(
        "github-actions",
        "trigger",
        "upyoke/platform",
        "deploy.yml",
        "--request-id",
        "deploy-json",
        "--correlation-input",
        "yoke_dispatch_id",
        "--project",
        "platform",
        "--json",
        result={"run_id": 41},
    )

    assert rc == 0
    assert err == ""
    envelope = json.loads(out)
    assert envelope["function"] == "github_actions.workflow.dispatch"
    assert envelope["result"]["run_id"] == 41
    assert _CAPTURED_REQUESTS[-1].payload["ref"] == "main"
    assert _CAPTURED_REQUESTS[-1].payload["inputs"] == {}


def test_trigger_once_relays_explicit_non_durable_operation() -> None:
    rc, out, err = _run(
        "github-actions",
        "trigger-once",
        "upyoke/buzz",
        "buzz-deploy.yml",
        "--ref",
        "main",
        "--input",
        "environment=production",
        "--project",
        "buzz",
        result={"run_id": 73},
    )

    assert rc == 0
    assert out == "73\n"
    assert err == ""
    request = _CAPTURED_REQUESTS[-1]
    assert request.function == "github_actions.workflow.dispatch_once"
    assert request.request_id
    assert request.payload == {
        "repo": "upyoke/buzz",
        "workflow": "buzz-deploy.yml",
        "ref": "main",
        "inputs": {"environment": "production"},
        "project": "buzz",
    }


@pytest.mark.parametrize("raw_input", ["missing-separator", "=missing-key"])
def test_trigger_rejects_malformed_inputs_before_relay(raw_input: str) -> None:
    rc, _out, err = _run(
        "github-actions",
        "trigger",
        "upyoke/platform",
        "deploy.yml",
        "--input",
        raw_input,
        "--request-id",
        "bad-input",
        "--correlation-input",
        "yoke_dispatch_id",
        "--project",
        "platform",
    )

    assert rc == 2
    assert "--input must be KEY=VALUE" in err
    assert _CAPTURED_REQUESTS == []


def test_find_run_prints_found_run_id() -> None:
    rc, out, err = _run(
        "github-actions",
        "find-run",
        "upyoke/platform",
        "deploy.yml",
        "abc123",
        "--project",
        "platform",
        result={"found": True, "run_id": 77},
    )

    assert rc == 0
    assert out == "77\n"
    assert err == ""
    assert _CAPTURED_REQUESTS[-1].payload == {
        "repo": "upyoke/platform",
        "workflow": "deploy.yml",
        "head_sha": "abc123",
        "project": "platform",
    }


def test_find_run_not_found_has_distinct_exit_code() -> None:
    rc, out, err = _run(
        "github-actions",
        "find-run",
        "upyoke/platform",
        "deploy.yml",
        "abc123",
        "--project",
        "platform",
        result={"found": False},
    )

    assert rc == 1
    assert out == "not_found\n"
    assert err == ""


@pytest.mark.parametrize(
    ("state", "message", "expected_rc"),
    [
        ("success", "success", 0),
        ("failed", "failed:failure", 1),
        ("waiting", "waiting", 2),
        ("running", "in_progress", 3),
    ],
)
def test_poll_preserves_point_in_time_state_exit_codes(
    state: str,
    message: str,
    expected_rc: int,
) -> None:
    rc, out, err = _run(
        "github-actions",
        "poll",
        "upyoke/platform",
        "77",
        "--project",
        "platform",
        result={"state": state, "message": message, "run_id": "77"},
    )

    assert rc == expected_rc
    assert out == f"{message}\n"
    assert err == ""
    request = _CAPTURED_REQUESTS[-1]
    assert request.function == "github_actions.wait_run"
    assert request.payload == {
        "repo": "upyoke/platform",
        "run_id": "77",
        "project": "platform",
    }


def test_jobs_count_relays_attempt_and_prints_count() -> None:
    rc, out, err = _run(
        "github-actions",
        "jobs-count",
        "upyoke/platform",
        "77",
        "--attempt",
        "3",
        "--project",
        "platform",
        result={"count": 6},
    )

    assert rc == 0
    assert out == "6\n"
    assert err == ""
    request = _CAPTURED_REQUESTS[-1]
    assert request.function == "github_actions.run.jobs_count"
    assert request.payload == {
        "repo": "upyoke/platform",
        "run_id": "77",
        "attempt": 3,
        "project": "platform",
    }
