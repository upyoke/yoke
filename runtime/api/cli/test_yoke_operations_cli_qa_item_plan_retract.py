"""CLI envelope for ``yoke qa item-plan retract``."""

from __future__ import annotations

import io
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

from yoke_cli.main import main as cli_main
from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionCallResponse,
)

TEST_ITEM_ID = 42
TEST_ITEM_REF = f"YOK-{TEST_ITEM_ID}"


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
        patch.dict("os.environ", {"YOKE_SESSION_ID": "qa-item-plan-retract-test"}),
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


def test_item_plan_retract_dispatches_the_item_target() -> None:
    result, request = _run(
        "qa",
        "item-plan",
        "retract",
        "--project",
        "yoke",
        "--item",
        TEST_ITEM_REF,
        "--plan-id",
        "17",
        "--transition",
        "release",
        "--reason",
        "attached the wrong standing post-deploy plan",
        "--source",
        "operator",
    )
    assert result == 0
    assert request.function == "qa.item_plan.retract"
    assert request.target.kind == "item"
    assert request.target.public_ref == TEST_ITEM_REF
    assert request.payload["plan_id"] == 17
    assert request.payload["transition_id"] == "release"
    assert request.payload["source"] == "operator"
    assert "wrong standing" in request.payload["reason"]
