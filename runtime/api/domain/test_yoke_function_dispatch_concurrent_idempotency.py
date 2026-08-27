"""Concurrent request-id replay coverage for side-effecting dispatches."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import threading

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
from runtime.api.fixtures.file_test_db import init_test_db


class _Request(BaseModel):
    pass


class _Response(BaseModel):
    pass


def test_concurrent_duplicate_dispatch_replays_one_handler_result(
    monkeypatch, tmp_path,
):
    reset_registry_for_tests()
    callers_ready = threading.Barrier(3)
    handlers_overlap = threading.Barrier(2)
    calls: list[int] = []
    calls_lock = threading.Lock()

    def handler(_request):
        with calls_lock:
            calls.append(len(calls) + 1)
            call_number = calls[-1]
        try:
            handlers_overlap.wait(timeout=3)
        except threading.BrokenBarrierError:
            pass
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
    monkeypatch.setattr(events_module, "emit_event", lambda *_a, **_k: None)
    request = FunctionCallRequest(
        function="relay.concurrent.claim",
        actor=ActorContext(actor_id="operator", session_id="session-1"),
        target=TargetRef(kind="item", item_id=42),
        request_id="shared-relay-request",
        payload={},
    )

    def call_dispatcher():
        callers_ready.wait(timeout=5)
        return dispatch(request, ambient_session_id="")

    try:
        with init_test_db(tmp_path):
            with ThreadPoolExecutor(max_workers=2) as executor:
                futures = [executor.submit(call_dispatcher) for _ in range(2)]
                callers_ready.wait(timeout=5)
                responses = [future.result(timeout=15) for future in futures]
    finally:
        reset_registry_for_tests()

    assert calls == [1]
    assert all(response.success for response in responses)
    assert [response.result for response in responses] == [
        {"claimed_batch": "batch-1"},
        {"claimed_batch": "batch-1"},
    ]
