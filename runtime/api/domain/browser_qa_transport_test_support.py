# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

import json

from typing import Any as Any, Dict as Dict, List as List

from unittest import mock as mock

from yoke_core.domain import browser_qa as browser_qa

from yoke_core.domain.browser_qa_steps import (
    _complete_run as _complete_run,
    _record_artifact as _record_artifact,
    _record_run as _record_run,
)

from yoke_contracts.api.function_call import (
    ActorContext as ActorContext,
    FunctionCallResponse,
    FunctionError,
)


def _ok(result: Dict[str, Any]) -> FunctionCallResponse:
    return FunctionCallResponse(
        success=True,
        function="x",
        version="v1",
        request_id="r",
        result=result,
    )


def _fail(code: str = "boom") -> FunctionCallResponse:
    return FunctionCallResponse(
        success=False,
        function="x",
        version="v1",
        request_id="r",
        error=FunctionError(code=code, message="nope"),
    )
