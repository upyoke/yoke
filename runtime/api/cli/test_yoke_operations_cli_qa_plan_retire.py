"""CLI envelopes for ``yoke qa plan retire`` and retired plan listing."""

from __future__ import annotations

import io
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

from yoke_cli.main import main as cli_main
from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionCallResponse,
)


def _run(*argv: str) -> tuple[int, FunctionCallRequest]:
    captured: list[FunctionCallRequest] = []

    def dispatch(request: FunctionCallRequest) -> FunctionCallResponse:
        captured.append(request)
        return FunctionCallResponse(
            success=True,
            function=request.function,
            request_id=request.request_id,
            version=request.version,
            result={},
        )

    with (
        patch.dict("os.environ", {"YOKE_SESSION_ID": "qa-plan-retire-test"}),
        patch(
            "yoke_core.domain.yoke_function_dispatch.dispatch",
            side_effect=dispatch,
        ),
        patch("yoke_cli.commands._helpers.ensure_handlers_loaded"),
        patch("sys.stdin", io.StringIO("")),
        redirect_stdout(io.StringIO()),
        redirect_stderr(io.StringIO()),
    ):
        result = cli_main(list(argv))
    assert captured
    return result, captured[-1]


def test_plan_retire_dispatches_a_global_target() -> None:
    result, request = _run(
        "qa",
        "plan",
        "retire",
        "hosted-installer-continue-correction",
        "--project",
        "yoke",
        "--reason",
        "only case is unrunnable",
    )
    assert result == 0
    assert request.function == "qa.plan.retire"
    assert request.target.kind == "global"
    assert request.payload == {
        "project": "yoke",
        "plan": "hosted-installer-continue-correction",
        "reason": "only case is unrunnable",
    }


def test_plan_list_sends_include_retired_only_when_asked() -> None:
    _, active = _run("qa", "plan", "list", "--project", "yoke")
    _, everything = _run("qa", "plan", "list", "--project", "yoke", "--include-retired")
    assert "include_retired" not in active.payload
    assert everything.payload["include_retired"] is True
