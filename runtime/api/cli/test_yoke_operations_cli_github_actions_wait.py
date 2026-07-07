"""``check-ci --wait`` no-run appearance-window coverage (sibling of
:mod:`test_yoke_operations_cli_github_actions`, 350-line cap split).

A just-pushed branch can report ``no_runs`` while GitHub registers the
triggered run; the client-side wait loop must wait (bounded) for the run to
appear before accepting ``no_runs`` and skipping CI (the fail-open race).
"""

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


@pytest.fixture(autouse=True)
def _reset_captured() -> None:
    _CAPTURED_REQUESTS.clear()


def _check_ci_response(state: str) -> dict:
    return {"state": state, "run_id": 7, "html_url": "https://x",
            "status": None, "conclusion": None}


def _stub_states(states: List[str]):
    responses = iter(states)

    def stub(request: FunctionCallRequest) -> FunctionCallResponse:
        _CAPTURED_REQUESTS.append(request)
        return FunctionCallResponse(
            success=True, function=request.function, version=request.version,
            request_id=request.request_id, result=_check_ci_response(next(responses)),
        )

    return stub


def _run_wait(*argv: str, stub, clock=None):
    from yoke_cli.commands.adapters import github_actions_wait as wait_mod

    sleeps: List[float] = []
    ticks = iter(clock or [0] * 16)
    with patch.dict("os.environ", {"YOKE_SESSION_ID": "test-session"}):
        with patch(
            "yoke_core.domain.yoke_function_dispatch.dispatch", side_effect=stub,
        ):
            with patch("yoke_cli.commands._helpers.ensure_handlers_loaded"), patch(
                "yoke_cli.commands.adapters.github_actions_wait.ensure_handlers_loaded"
            ):
                with patch.object(wait_mod, "now", lambda: next(ticks)), \
                        patch.object(wait_mod, "sleep", sleeps.append):
                    with redirect_stdout(io.StringIO()) as out, redirect_stderr(io.StringIO()):
                        rc = cli_main(list(argv))
    return rc, sleeps, out.getvalue()


def test_wait_for_no_runs_waits_for_run_to_appear() -> None:
    from yoke_core.domain.github_actions_run_monitoring import (
        CHECK_CI_POLL_INTERVAL_SEC,
    )

    # no_runs (run not yet registered) -> running -> passed: the gate WAITS for
    # the run to appear rather than skipping CI (fail-open).
    rc, sleeps, _out = _run_wait(
        "github-actions", "check-ci", "o/r", "ci.yml", "--wait",
        stub=_stub_states(["no_runs", "running", "passed"]),
        clock=[0, 10, 20],
    )
    assert rc == 0
    assert len(_CAPTURED_REQUESTS) == 3
    assert sleeps == [CHECK_CI_POLL_INTERVAL_SEC] * 2


def test_wait_accepts_no_runs_after_appearance_window() -> None:
    # The run never registers; once the appearance window elapses no_runs is
    # genuine (branch runs no CI), so the gate returns no_runs and skips.
    rc, _sleeps, out = _run_wait(
        "github-actions", "check-ci", "o/r", "ci.yml", "--wait", "--json",
        stub=_stub_states(["no_runs", "no_runs"]),
        clock=[0, 10, 95],
    )
    assert rc == 0
    assert '"state": "no_runs"' in out
