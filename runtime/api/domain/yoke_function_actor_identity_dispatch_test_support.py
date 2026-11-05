# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

import unittest

from typing import Optional

from unittest.mock import patch

from pydantic import BaseModel

from yoke_core.domain import yoke_function_actor_identity as identity_module

from yoke_core.domain import yoke_function_dispatch as dispatch_module

from yoke_core.domain import yoke_function_dispatch_events as events_module

from yoke_core.domain.dispatch_actor_requirement import numeric_actor_id

from yoke_core.domain.yoke_function_actor_identity import ActorLookup

from yoke_core.domain.yoke_function_permission_types import DispatchPermission

from yoke_core.domain.yoke_function_dispatch import dispatch

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    FunctionWarning,
    HandlerOutcome,
    TargetRef,
)

from yoke_core.domain.yoke_function_registry import (
    register,
    reset_registry_for_tests,
)


class _Req(BaseModel):
    pass


class _Resp(BaseModel):
    pass


def _ok_handler(_request):
    return HandlerOutcome(result_payload={"ok": True}, primary_success=True)


def _warning_handler(_request):
    return HandlerOutcome(
        result_payload={"ok": True},
        primary_success=True,
        warnings=[FunctionWarning(code="downstream", step="x", detail="fail")],
    )


def _make_request(
    *,
    function: str = "test.family.op",
    payload_session: str = "payload-s",
    actor_id: Optional[str] = None,
    item_id: int = 7,
    request_id: Optional[str] = None,
) -> FunctionCallRequest:
    return FunctionCallRequest(
        function=function,
        actor=ActorContext(actor_id=actor_id, session_id=payload_session),
        target=TargetRef(kind="item", item_id=item_id),
        request_id=request_id,
    )


class _Recorder:
    def __init__(self):
        self.calls = []

    def __call__(self, *a, **kw):
        self.calls.append({"args": a, "kwargs": kw})

    def names(self):
        return [
            c["args"][0] if c["args"] else c["kwargs"].get("event_name")
            for c in self.calls
        ]


class _IntegrationBase(unittest.TestCase):
    resolver_lookup = ActorLookup(actor_id=None, session_found=True)
    operating_actor: Optional[str] = "42"

    def _permission(self, entry, request):
        # A bound numeric actor is authorized here: these tests cover identity
        # binding. An actor-less call meets the real gate, which refuses
        # side effects before any database read.
        if numeric_actor_id(request.actor.actor_id) is not None:
            return DispatchPermission(None, None, None)
        return self._real_permission(entry, request)

    def setUp(self):
        reset_registry_for_tests()
        self._recorder = _Recorder()
        self._real_permission = dispatch_module.dispatch_permission_for_request
        self._patchers = [
            patch.object(
                dispatch_module, "dispatch_permission_for_request", self._permission
            ),
            patch(
                "yoke_core.domain.session_less_actor_binding.operating_actor_id",
                lambda: self.operating_actor,
            ),
            patch.object(events_module, "emit_event", self._recorder),
            patch.object(
                dispatch_module,
                "_idempotency_lookup",
                lambda *_a, **_k: None,
            ),
            patch.object(
                identity_module,
                "_default_actor_id_resolver",
                lambda _sid: self.resolver_lookup,
            ),
        ]
        for p in self._patchers:
            p.start()

    def tearDown(self):
        for p in reversed(self._patchers):
            p.stop()
        reset_registry_for_tests()

    def _register(
        self,
        function_id,
        handler=_ok_handler,
        side_effects=(),
        ambient_session_required=True,
    ):
        register(
            function_id,
            handler,
            _Req,
            _Resp,
            stability="stable",
            owner_module="yoke_core.domain.test_actor_identity",
            target_kinds=["item"],
            side_effects=list(side_effects),
            emitted_event_names=[],
            guardrails=[],
            adapter_status="live",
            ambient_session_required=ambient_session_required,
        )

    def _called_events(self, name="YokeFunctionCalled"):
        return [c for c in self._recorder.calls if c["args"] and c["args"][0] == name]
