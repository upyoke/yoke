"""CLI envelope for ``yoke qa requirement rebind-target``."""

from __future__ import annotations

import io
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

from yoke_cli.main import main as cli_main
from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionCallResponse,
)


def _run(*argv: str):
    captured = []

    def dispatch(request: FunctionCallRequest) -> FunctionCallResponse:
        captured.append(request)
        return FunctionCallResponse(
            success=True,
            function=request.function,
            version=request.version,
            request_id=request.request_id,
            result={
                "requirement_id": 101,
                "from_digest": "aa",
                "to_digest": "bb",
                "already_current": False,
            },
        )

    stdout = io.StringIO()
    stderr = io.StringIO()
    with (
        patch.dict("os.environ", {"YOKE_SESSION_ID": "test-session"}),
        patch(
            "yoke_core.domain.yoke_function_dispatch.dispatch",
            side_effect=dispatch,
        ),
        patch("yoke_cli.commands._helpers.ensure_handlers_loaded"),
        redirect_stdout(stdout),
        redirect_stderr(stderr),
    ):
        rc = cli_main(list(argv))
    return rc, stdout.getvalue(), stderr.getvalue(), captured


def test_rebind_target_dispatches_requirement_target():
    rc, out, _err, calls = _run(
        "qa",
        "requirement",
        "rebind-target",
        "--requirement-id",
        "101",
        "--rationale",
        "environment declaration corrected",
    )
    assert rc == 0
    assert "101" in out
    assert calls[0].function == "qa.requirement.rebind_target"
    assert calls[0].target.qa_requirement_id == 101
    assert calls[0].payload == {"rationale": "environment declaration corrected"}
