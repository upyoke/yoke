"""Dispatcher coverage for project-role permission refusals."""

from __future__ import annotations

import os
from unittest.mock import patch

from pydantic import BaseModel

from yoke_core.domain import yoke_function_dispatch as dispatch_module
from yoke_core.domain import yoke_function_dispatch_events as events_module
from yoke_core.domain.yoke_function_dispatch import dispatch
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    FunctionCallResponse,
    FunctionError,
    HandlerOutcome,
    TargetRef,
)
from yoke_core.domain.yoke_function_permissions import DispatchPermission
from yoke_core.domain.yoke_function_registry import (
    register,
    reset_registry_for_tests,
)


class _Req(BaseModel):
    pass


class _Resp(BaseModel):
    pass


class _Recorder:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def __call__(self, *args, **kwargs) -> None:
        self.calls.append({"args": args, "kwargs": kwargs})

    def names(self) -> list[str]:
        return [call["args"][0] for call in self.calls if call["args"]]


def test_permission_denied_skips_handler_and_emits_event():
    called = False

    def handler(_request):
        nonlocal called
        called = True
        return HandlerOutcome(result_payload={"status": "unexpected"})

    reset_registry_for_tests()
    recorder = _Recorder()
    register(
        "items.structured_field.replace",
        handler,
        _Req,
        _Resp,
        stability="stable",
        owner_module=__name__,
        target_kinds=["item"],
        side_effects=["db_write"],
        emitted_event_names=[],
        guardrails=[],
        adapter_status="live",
    )
    request = FunctionCallRequest(
        function="items.structured_field.replace",
        actor=ActorContext(actor_id="7", session_id="s-1"),
        target=TargetRef(kind="item", item_id=42),
    )
    error = FunctionCallResponse(
        success=False,
        function="items.structured_field.replace",
        version="1",
        request_id=request.request_id,
        result={},
        warnings=[],
        error=FunctionError(
            code="permission_denied",
            message="actor 7 lacks items.write on project 1",
        ),
        event_ids=[],
    )
    try:
        with patch.object(events_module, "emit_event", recorder):
            with patch.object(dispatch_module, "_idempotency_lookup", lambda *_: None):
                with patch.object(
                    dispatch_module,
                    "dispatch_permission_for_request",
                    return_value=DispatchPermission(
                        "items.write",
                        1,
                        "yoke",
                        error=error,
                    ),
                ):
                    with patch.dict(os.environ, {"YOKE_SESSION_ID": "s-1"}):
                        resp = dispatch(request)
    finally:
        reset_registry_for_tests()

    assert not resp.success
    assert resp.error is not None
    assert resp.error.code == "permission_denied"
    assert not called
    assert "YokeFunctionPermissionDenied" in recorder.names()
    denied_call = next(
        call for call in recorder.calls
        if call["args"] and call["args"][0] == "YokeFunctionPermissionDenied"
    )
    assert denied_call["kwargs"]["request_id"] == request.request_id
