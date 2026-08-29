"""Dispatch-path tests for ``yoke qa gate-summary``."""

from __future__ import annotations

import io
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

import pytest

from yoke_cli.main import main as cli_main
from yoke_contracts.api.function_call import FunctionCallRequest, FunctionCallResponse


_CAPTURED_REQUESTS: list[FunctionCallRequest] = []


def _stub_ok(request: FunctionCallRequest) -> FunctionCallResponse:
    _CAPTURED_REQUESTS.append(request)
    return FunctionCallResponse(
        success=True,
        function=request.function,
        version=request.version,
        request_id=request.request_id,
        result={"echo": True},
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


class TestQaGateSummary:
    def test_item_target_with_transition_payload(self) -> None:
        rc = _run(
            "qa",
            "gate-summary",
            "--item",
            "1833",
            "--target",
            "reviewed-implementation",
        )
        assert rc == 0
        req = _CAPTURED_REQUESTS[-1]
        assert req.function == "qa.gate_summary.run"
        assert req.target.kind == "item"
        assert req.target.public_ref == "1833"
        assert req.payload == {"transition": "reviewed-implementation"}

    def test_epic_task_target(self) -> None:
        rc = _run(
            "qa",
            "gate-summary",
            "--epic-id",
            "1704",
            "--task-num",
            "5",
            "--target",
            "implemented",
        )
        assert rc == 0
        req = _CAPTURED_REQUESTS[-1]
        assert req.target.kind == "epic_task"
        assert req.target.epic_id == 1704
        assert req.target.task_num == 5
        assert req.payload == {"transition": "implemented"}

    def test_invalid_target_choice_returns_two(self) -> None:
        rc = _run(
            "qa",
            "gate-summary",
            "--item",
            "1833",
            "--target",
            "done",
        )
        assert rc == 2
        assert _CAPTURED_REQUESTS == []

    def test_missing_target_shape_returns_two(self) -> None:
        rc = _run(
            "qa",
            "gate-summary",
            "--target",
            "implemented",
        )
        assert rc == 2
        assert _CAPTURED_REQUESTS == []
