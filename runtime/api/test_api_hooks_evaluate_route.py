"""Route test for ``POST /v1/hooks/evaluate`` (auth-gated)."""

from __future__ import annotations

from runtime.api.api_hooks_evaluate_route_test_support import (
    _request_body as _request_body,
    client as client,
    hooks_db as hooks_db,
    pytestmark as pytestmark,
)


import os
import sys
import time
import types


sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))


def test_hooks_evaluate_benign_event_allows(client) -> None:
    response = client.post("/v1/hooks/evaluate", json=_request_body())

    assert response.status_code == 200
    payload = response.json()
    assert payload["hook_schema"] == 1
    assert payload["exit_code"] == 0
    assert payload["stdout"] == ""
    assert payload["degraded"] == []
    assert payload["outcome"] == "completed"
    assert isinstance(payload["wait_ms"], int) and payload["wait_ms"] >= 0


def test_hooks_evaluate_honors_deadline_and_marks_degraded(
    client,
    monkeypatch,
) -> None:
    from yoke_core.hooks import runner as runner_module
    from yoke_core.hooks.types import HookDecision, Next, Outcome

    def slow_evaluate(context) -> HookDecision:  # pragma: no cover — times out
        time.sleep(2.0)
        return HookDecision(outcome=Outcome.NOOP, next=Next.CONTINUE)

    slow = types.ModuleType("remote_hook_route.fake_slow")
    slow.evaluate = slow_evaluate
    monkeypatch.setitem(sys.modules, "remote_hook_route.fake_slow", slow)
    monkeypatch.setattr(
        runner_module,
        "chain_for",
        lambda *a, **k: ["remote_hook_route.fake_slow", "remote_hook_route.fake_slow"],
    )

    started = time.monotonic()
    response = client.post(
        "/v1/hooks/evaluate",
        json=_request_body(deadline_ms=300),
    )
    elapsed_ms = (time.monotonic() - started) * 1000

    assert response.status_code == 200
    payload = response.json()
    assert payload["exit_code"] == 0
    assert "deadline_exhausted" in payload["degraded"]
    # The propagated 300ms budget governs, not the 2s the policy wanted.
    assert elapsed_ms < 1500


def test_hooks_evaluate_unsupported_schema_is_typed_400(client) -> None:
    response = client.post(
        "/v1/hooks/evaluate",
        json=_request_body(hook_schema=99),
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "UNSUPPORTED_HOOK_SCHEMA"


def test_hooks_evaluate_requires_auth(client) -> None:
    response = client.post(
        "/v1/hooks/evaluate",
        json=_request_body(),
        headers={"Authorization": "Bearer not-a-real-token"},
    )

    assert response.status_code == 401
