"""CLI tests for ``yoke github-actions wait-run``."""

from __future__ import annotations

import io
from contextlib import redirect_stderr, redirect_stdout
from typing import Any, Dict, List
from unittest.mock import patch

import pytest

from yoke_cli.commands.adapters import github_actions_run_wait as wait_mod
from yoke_cli.main import main as cli_main
from yoke_contracts.api.function_call import FunctionCallResponse


_CALLS: List[Dict[str, Any]] = []


@pytest.fixture(autouse=True)
def _reset_calls() -> None:
    _CALLS.clear()


def _response(function_id: str, state: str, *, message: str) -> FunctionCallResponse:
    return FunctionCallResponse(
        success=True,
        function=function_id,
        version="v1",
        request_id="test-request",
        result={
            "state": state,
            "run_id": "123",
            "status": "in_progress" if state == "running" else "completed",
            "conclusion": None,
            "html_url": "https://github.com/o/r/actions/runs/123",
            "message": message,
        },
    )


def _run_wait(*argv: str, states: List[tuple[str, str]], clock=None):
    responses = iter(states)
    sleeps: List[float] = []
    ticks = iter(clock or [0] * 16)

    def stub_call_dispatcher(**kwargs):
        _CALLS.append(kwargs)
        state, message = next(responses)
        return _response(kwargs["function_id"], state, message=message)

    with patch.dict("os.environ", {"YOKE_SESSION_ID": "test-session"}):
        with patch.object(wait_mod, "call_dispatcher", side_effect=stub_call_dispatcher), \
                patch.object(wait_mod, "ensure_handlers_loaded"), \
                patch.object(wait_mod, "now", lambda: next(ticks)), \
                patch.object(wait_mod, "sleep", sleeps.append):
            with redirect_stdout(io.StringIO()) as out, \
                    redirect_stderr(io.StringIO()) as err:
                rc = cli_main(list(argv))
    return rc, sleeps, out.getvalue(), err.getvalue()


def test_registry_maps_wait_run_to_single_shot_read() -> None:
    from yoke_cli.commands.registry import SUBCOMMAND_REGISTRY

    assert SUBCOMMAND_REGISTRY[("github-actions", "wait-run")][0] == (
        "github_actions.wait_run"
    )


def test_wait_run_dispatches_single_shot_reads_until_success() -> None:
    rc, sleeps, out, _err = _run_wait(
        "github-actions", "wait-run", "o/r", "123",
        "--project", "yoke",
        states=[("waiting", "waiting"), ("running", "in_progress"),
                ("success", "success")],
        clock=[0, 10, 20],
    )
    assert rc == 0
    assert out.strip() == "success"
    assert sleeps == [wait_mod.RUN_WAIT_POLL_INTERVAL_SEC] * 2
    assert [call["function_id"] for call in _CALLS] == [
        "github_actions.wait_run",
        "github_actions.wait_run",
        "github_actions.wait_run",
    ]
    assert _CALLS[0]["payload"] == {
        "repo": "o/r",
        "run_id": "123",
        "project": "yoke",
    }


def test_wait_run_failure_preserves_failure_exit_code() -> None:
    rc, sleeps, out, _err = _run_wait(
        "github-actions", "wait-run", "o/r", "123",
        "--project", "yoke",
        states=[("failed", "failed:failure")],
    )
    assert rc == 1
    assert sleeps == []
    assert out.strip() == "failed:failure"


def test_wait_run_timeout_returns_three_and_json_state() -> None:
    rc, sleeps, out, _err = _run_wait(
        "github-actions", "wait-run", "o/r", "123",
        "--timeout", "600", "--json", "--project", "yoke",
        states=[("running", "in_progress"), ("running", "in_progress")],
        clock=[0, 601],
    )
    assert rc == 3
    assert sleeps == []
    assert '"state": "timeout"' in out
    assert '"message": "timeout:in_progress"' in out


def test_wait_run_dispatch_error_stops_polling() -> None:
    def stub_call_dispatcher(**kwargs):
        _CALLS.append(kwargs)
        return FunctionCallResponse(
            success=False,
            function=kwargs["function_id"],
            version="v1",
            request_id="test-request",
            error={"code": "rest_transport_error", "message": "boom"},
        )

    with patch.dict("os.environ", {"YOKE_SESSION_ID": "test-session"}):
        with patch.object(wait_mod, "call_dispatcher", side_effect=stub_call_dispatcher), \
                patch.object(wait_mod, "ensure_handlers_loaded"):
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                rc = cli_main([
                    "github-actions", "wait-run", "o/r", "123",
                    "--project", "yoke",
                ])
    assert rc == 1
    assert len(_CALLS) == 1


def test_wait_run_repo_without_slash_returns_usage_error() -> None:
    rc, _sleeps, _out, _err = _run_wait(
        "github-actions", "wait-run", "no-slash", "123",
        "--project", "yoke",
        states=[("success", "success")],
    )
    assert rc == 2
    assert _CALLS == []


def test_wait_run_missing_args_prints_sanctioned_usage() -> None:
    with redirect_stdout(io.StringIO()) as out, redirect_stderr(io.StringIO()) as err:
        rc = cli_main(["github-actions", "wait-run"])
    assert rc == 2
    assert out.getvalue() == ""
    assert "yoke github-actions wait-run" in err.getvalue()
