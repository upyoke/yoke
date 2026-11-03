"""Concurrent request-id replay coverage for side-effecting dispatches."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import threading
from time import monotonic

from pydantic import BaseModel

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    HandlerOutcome,
    TargetRef,
)
from yoke_core.domain import yoke_function_dispatch_events as events_module
from yoke_core.domain.yoke_function_dispatch import dispatch
from yoke_core.domain.yoke_function_registry import (
    register,
    reset_registry_for_tests,
)
from runtime.api.fixtures.dispatch_actor import authorize_every_dispatch
from runtime.api.fixtures.file_test_db import init_test_db


class _Request(BaseModel):
    pass


class _Response(BaseModel):
    pass


def test_concurrent_duplicate_dispatch_replays_one_handler_result(
    monkeypatch, tmp_path,
):
    reset_registry_for_tests()
    handler_started = threading.Event()
    handler_release = threading.Event()
    calls: list[int] = []
    calls_lock = threading.Lock()

    def handler(_request):
        with calls_lock:
            calls.append(len(calls) + 1)
            call_number = calls[-1]
        handler_started.set()
        assert handler_release.wait(timeout=10)
        return HandlerOutcome(
            result_payload={"claimed_batch": f"batch-{call_number}"},
            primary_success=True,
        )

    register(
        "relay.concurrent.claim",
        handler,
        _Request,
        _Response,
        stability="stable",
        owner_module="yoke_core.domain.test_concurrent_dispatch",
        target_kinds=["item"],
        side_effects=["session_control_jobs_lease"],
        emitted_event_names=["FakeEvent"],
        guardrails=[],
        adapter_status="live",
    )
    emitted = []
    monkeypatch.setattr(
        events_module, "emit_event", lambda name, **kw: emitted.append((name, kw))
    )
    request = FunctionCallRequest(
        function="relay.concurrent.claim",
        actor=ActorContext(actor_id="operator", session_id="session-1"),
        target=TargetRef(kind="item", item_id=42),
        request_id="shared-relay-request",
        payload={},
    )


    try:
        with init_test_db(tmp_path), authorize_every_dispatch():
            with ThreadPoolExecutor(max_workers=1) as executor:
                original = executor.submit(dispatch, request, ambient_session_id="")
                try:
                    assert handler_started.wait(timeout=5)
                    started = monotonic()
                    duplicate = dispatch(request, ambient_session_id="")
                    waited = monotonic() - started
                finally:
                    handler_release.set()
                first = original.result(timeout=15)
            replay = dispatch(request, ambient_session_id="")
    finally:
        reset_registry_for_tests()

    assert calls == [1]
    assert not duplicate.success
    assert duplicate.error.code == "idempotency_request_in_flight"
    assert "same request_id" in duplicate.error.message
    assert waited < 1
    assert first.success and replay.success
    assert first.result == replay.result == {"claimed_batch": "batch-1"}

    refusals = [
        event for name, event in emitted
        if name == "YokeFunctionCalled"
        and event["context"].get("error_code") == "idempotency_request_in_flight"
    ]
    assert len(refusals) == 1
    assert refusals[0]["outcome"] == "failed"
    assert refusals[0]["duration_ms"] is None  # No handler ran for the duplicate.
