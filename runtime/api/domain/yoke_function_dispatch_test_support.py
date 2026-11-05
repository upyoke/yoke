# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

import json

import os

import shutil

import tempfile

import unittest

from pathlib import Path

from typing import Any, Dict, Optional

from unittest.mock import patch

from pydantic import BaseModel

from runtime.api.fixtures.dispatch_actor import authorize_every_dispatch

from yoke_core.domain import yoke_function_dispatch as dispatch_module

from yoke_core.domain import yoke_function_dispatch_claims as claims_module

from yoke_core.domain import yoke_function_dispatch_events as events_module

from yoke_core.domain.yoke_function_dispatch_claim_evidence import (
    CLAIM_VERIFICATION_ALLOWED,
    CLAIM_VERIFICATION_PHASE,
    WORK_CLAIM_AUTHORITY,
)

from yoke_core.domain.observe_anomaly import detect_anomalies

from yoke_core.domain.observe_event_emission import build_envelope, insert_event

from yoke_core.domain.observe_parsing import parse_hook_event

from runtime.api.fixtures.file_test_db import connect_test_db

from runtime.api.lane_ref_test_support import add_minimal_item

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

from runtime.api.observe_full_test_helpers import make_events_db_file


class _Req(BaseModel):
    pass


class _Resp(BaseModel):
    pass


def _stable_kwargs(**overrides):
    base = {
        "stability": "stable",
        "owner_module": "yoke_core.domain.test_dispatch",
        "target_kinds": ["item"],
        "side_effects": [],
        "emitted_event_names": ["FakeEvent"],
        "guardrails": [],
        "adapter_status": "live",
    }
    base.update(overrides)
    return base


def _ok_handler(_request):
    return HandlerOutcome(result_payload={"status": "ok"}, primary_success=True)


def _make_request(
    function: str,
    *,
    item_id: int = 42,
    session_id: str = "s-1",
    request_id: Optional[str] = None,
    kind: str = "item",
    epic_id: Optional[int] = None,
    task_num: Optional[int] = None,
    claim_id: Optional[int] = None,
) -> FunctionCallRequest:
    target = TargetRef(
        kind=kind,
        item_id=item_id if kind == "item" else None,
        epic_id=epic_id,
        task_num=task_num,
        claim_id=claim_id,
    )
    return FunctionCallRequest(
        function=function,
        actor=ActorContext(actor_id="op", session_id=session_id),
        target=target,
        request_id=request_id,
    )


class _EventRecorder:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        self.calls.append({"args": args, "kwargs": kwargs})

    def names(self) -> list[str]:
        return [
            c["args"][0] if c["args"] else c["kwargs"].get("event_name", "")
            for c in self.calls
        ]


class _DispatcherTestBase(unittest.TestCase):
    """Shared scaffolding: silence emit_event and clear the registry."""

    def setUp(self) -> None:
        reset_registry_for_tests()
        # Silence every event emission path + the idempotency-ledger
        # write/read so unit dispatches never touch the shared test DB.
        self._patchers = [
            patch.object(events_module, "emit_event", _EventRecorder()),
            patch.object(events_module, "record_call", lambda *_a, **_k: True),
            patch.object(
                dispatch_module, "_idempotency_lookup", lambda *_a, **_k: None
            ),
            authorize_every_dispatch(),
        ]
        for p in self._patchers:
            p.start()

    def tearDown(self) -> None:
        for p in reversed(self._patchers):
            p.stop()
        reset_registry_for_tests()
