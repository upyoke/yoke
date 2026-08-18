"""Shared fixtures for interactive QA plan-edit CLI contract tests."""

from __future__ import annotations

import io
from contextlib import redirect_stderr, redirect_stdout
from typing import Callable
from unittest.mock import patch

from yoke_cli.main import main as cli_main
from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionCallResponse,
    FunctionError,
)


PLAN = {
    "slug": "release-readiness",
    "name": "Release readiness",
    "description": "Release proof.",
    "success_policy_id": "all-pass",
    "success_policy_params": {},
    "target_environment": None,
    "updated_at": "2026-07-27T10:00:00Z",
    "cases": [
        {
            "case_key": "backend-suite",
            "position": 1,
            "method_id": "command",
            "instructions": "Run it.",
            "expected_outcome": "It passes.",
            "method_config": {"command": "pytest"},
            "success_policy_id": None,
            "success_policy_params": None,
            "host_baselines": [],
            "entry_surface": None,
            "required_completion": None,
        }
    ],
}
EDIT_ARGS = (
    "qa",
    "plan",
    "edit",
    "release-readiness",
    "--project",
    "yoke",
)
CONTEXT_ARGS = EDIT_ARGS[:4]


def _response(
    request: FunctionCallRequest,
    *,
    result: dict | None = None,
    error: FunctionError | None = None,
) -> FunctionCallResponse:
    return FunctionCallResponse(
        success=error is None,
        function=request.function,
        version=request.version,
        request_id=request.request_id,
        result=result or {},
        error=error,
    )


def _dispatch(
    requests: list[FunctionCallRequest],
    *,
    edit_error: FunctionError | None = None,
) -> Callable[[FunctionCallRequest], FunctionCallResponse]:
    def dispatch(request: FunctionCallRequest) -> FunctionCallResponse:
        requests.append(request)
        if request.function == "qa.plan.list":
            return _response(
                request,
                result={
                    "rows": [
                        {
                            "id": 7,
                            "project": "yoke",
                            "slug": "release-readiness",
                        }
                    ],
                },
            )
        if request.function == "qa.plan.get":
            return _response(request, result={"plan": PLAN})
        if request.function == "qa.plan.edit":
            if edit_error is not None:
                return _response(request, error=edit_error)
            return _response(
                request,
                result={
                    "plan_id": 7,
                    "project_id": 1,
                    "project": "yoke",
                    "slug": "release-readiness",
                    "case_count": 1,
                    "updated_at": "2026-07-27T10:01:00.000001Z",
                    "unchanged": False,
                },
            )
        raise AssertionError(f"unexpected function {request.function}")

    return dispatch


def run_cli(
    requests: list[FunctionCallRequest],
    editor,
    *argv: str,
    edit_error: FunctionError | None = None,
) -> tuple[int, str, str]:
    stdout = io.StringIO()
    stderr = io.StringIO()
    with (
        patch.dict("os.environ", {"YOKE_SESSION_ID": "qa-plan-edit-test"}),
        patch(
            "yoke_core.domain.yoke_function_dispatch.dispatch",
            side_effect=_dispatch(requests, edit_error=edit_error),
        ),
        patch("yoke_cli.commands._helpers.ensure_handlers_loaded"),
        patch(
            "yoke_cli.commands.adapters.qa_plan_edit.subprocess.run",
            side_effect=editor,
        ),
        redirect_stdout(stdout),
        redirect_stderr(stderr),
    ):
        result = cli_main(list(argv))
    return result, stdout.getvalue(), stderr.getvalue()
