# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

from runtime.api.domain.yoke_function_dispatch_test_support import _ok_handler as _ok_handler

import unittest

from typing import Optional

from unittest.mock import patch

from pydantic import BaseModel

from yoke_core.domain import yoke_function_dispatch as dispatch_module

from yoke_core.domain import yoke_function_dispatch_claims as claims_module

from yoke_core.domain import yoke_function_dispatch_events as events_module

from yoke_core.domain.yoke_function_dispatch import dispatch

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
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


def _stable_kwargs(**overrides):
    base = {
        "stability": "stable",
        "owner_module": "yoke_core.domain.test_dispatch_claims",
        "target_kinds": ["item"],
        "side_effects": [],
        "emitted_event_names": ["FakeEvent"],
        "guardrails": [],
        "adapter_status": "live",
    }
    base.update(overrides)
    return base


def _make_request(
    function: str,
    *,
    item_id: int = 42,
    session_id: str = "s-1",
    kind: str = "item",
    epic_id: Optional[int] = None,
    task_num: Optional[int] = None,
    claim_id: Optional[int] = None,
    deployment_run_id: Optional[str] = None,
    payload: Optional[dict] = None,
) -> FunctionCallRequest:
    target = TargetRef(
        kind=kind,
        item_id=item_id if kind == "item" else None,
        epic_id=epic_id,
        task_num=task_num,
        claim_id=claim_id,
        deployment_run_id=deployment_run_id,
    )
    return FunctionCallRequest(
        function=function,
        actor=ActorContext(actor_id="op", session_id=session_id),
        target=target,
        payload=payload or {},
    )


class _ClaimMatrixSuite(unittest.TestCase):
    def setUp(self) -> None:
        reset_registry_for_tests()
        self._patchers = [
            patch.object(events_module, "emit_event"),
            patch.object(
                dispatch_module,
                "_idempotency_lookup",
                lambda *_a, **_k: None,
            ),
            # Bind ambient session to the same id the test envelopes use so the
            # dispatcher's actor-identity gate stays out of the way and the
            # verify_claim matrix below is what actually runs.
            patch.dict(
                "os.environ",
                {"YOKE_SESSION_ID": "s-1"},
                clear=False,
            ),
        ]
        for p in self._patchers:
            p.start()

    def tearDown(self) -> None:
        for p in reversed(self._patchers):
            p.stop()
        reset_registry_for_tests()
