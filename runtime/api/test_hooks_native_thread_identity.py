"""Harness-native thread identity across the hook relay wire."""

from __future__ import annotations

from fastapi import BackgroundTasks
import json

from yoke_core.api.routes import hooks as routes
from yoke_core.hooks import remote_entry
from yoke_core.hooks.remote_entry import RemoteEvaluation
from yoke_core.api.http_auth import HttpAuthContext
from yoke_core.domain.session_scope_identity import HookScopeDecision


def test_route_preserves_native_thread_id(monkeypatch) -> None:
    captured: dict = {}
    monkeypatch.setattr(
        routes,
        "require_auth_context",
        lambda _request: HttpAuthContext(1, 2, "test"),
    )
    monkeypatch.setattr(
        routes,
        "_authorize_scope",
        lambda *_: (HookScopeDecision(project_id=1, project_slug="example"), None),
    )
    monkeypatch.setattr(
        routes,
        "evaluate_remote",
        lambda **kwargs: (
            captured.update(kwargs)
            or RemoteEvaluation(
                stdout="",
                exit_code=0,
                degraded=(),
                wait_ms=1,
                outcome="completed",
                denial_audit={},
            )
        ),
    )
    monkeypatch.setattr(routes, "record_histogram", lambda *_a, **_k: None)
    monkeypatch.setattr(routes, "record_counter", lambda *_a, **_k: None)
    monkeypatch.setattr(routes, "collect_execution_provenance", lambda: {})
    request = routes.HookEvaluateRequest(
        event_name="SessionStart",
        stdin=json.dumps({"session_id": "sid-1", "identity_stamped": True}),
        executor="cursor-cli",
        project_id=1,
        native_thread_id="cursor-conversation",
    )

    response = routes.post_hooks_evaluate(object(), request, BackgroundTasks())

    assert response.status_code == 200
    assert captured["native_thread_id"] == "cursor-conversation"


def test_remote_entry_merges_native_thread_into_registration_payload(
    monkeypatch,
) -> None:
    captured: dict = {}
    monkeypatch.setattr(remote_entry, "resolve_total_timeout_ms", lambda: 1000)
    monkeypatch.setattr(remote_entry, "resolve_capability", lambda _executor: object())

    def _run(_event, *, controls, **_kwargs):
        captured.update(controls.payload_extra)
        return "", 0

    monkeypatch.setattr(remote_entry, "run_event", _run)
    remote_entry.evaluate_remote(
        "SessionStart",
        "{}",
        "cursor-cli",
        None,
        1000,
        native_thread_id="cursor-conversation",
    )

    assert captured["native_thread_id"] == "cursor-conversation"
