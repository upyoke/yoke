# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

import json

import unittest

from typing import Any, Dict

from unittest.mock import patch

from yoke_core.domain import yoke_function_dispatch as dispatch_module

from yoke_core.domain import yoke_function_dispatch_events as events_module

from yoke_core.domain.yoke_function_dispatch import dispatch

from yoke_core.domain.yoke_function_dispatch_events import emit_permission_denied

from yoke_core.domain.yoke_function_dispatch_failure_context import (
    FAILURE_TEXT_MAX_CHARS,
)

from yoke_core.domain.yoke_function_registry import register

from yoke_contracts.api.function_call import (
    FunctionError,
    FunctionWarning,
    HandlerOutcome,
)

from runtime.api.domain.yoke_function_dispatch_test_support import (
    _DispatcherTestBase,
    _Req,
    _Resp,
    _make_request,
    _ok_handler,
    _stable_kwargs,
)

_BIG_RESULT = {
    "sessions": [{"session_id": f"s-{n}", "note": "x" * 180} for n in range(100)]
}


def _big_result_handler(_request):
    return HandlerOutcome(result_payload=dict(_BIG_RESULT), primary_success=True)


class CompactEventBase(_DispatcherTestBase):
    """Dispatch one registered handler and return its called-event context."""

    def _context_for(self, function_id: str, handler: Any, **reg) -> Dict[str, Any]:
        register(function_id, handler, _Req, _Resp, **_stable_kwargs(**reg))
        dispatch(_make_request(function_id))
        return self._called_context()

    def _called_context(self) -> Dict[str, Any]:
        calls = events_module.emit_event.calls  # type: ignore[attr-defined]
        called = [
            c for c in calls if c["args"] and c["args"][0] == "YokeFunctionCalled"
        ]
        self.assertEqual(len(called), 1)
        return called[0]["kwargs"]["context"]
