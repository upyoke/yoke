"""Each steering report reply names its path in the call's telemetry.

Latency acceptance measures full builds only, so the composed, skipped and
questions-only replies must be distinguishable in ``YokeFunctionCalled``.
"""

from unittest.mock import patch

from runtime.api.domain.handlers.test_steering_report import (
    SESSION_ALPHA,
    PROJECT_ALPHA,
    _patch_report_dependencies,
    _request,
    acquire_steering,
    seed_standard_steering_world,
)
from yoke_contracts.api.function_call import ActorContext, FunctionCallRequest, TargetRef
from yoke_core.domain.handlers.steering_report import handle_get


def _payload_request(payload):
    return FunctionCallRequest(
        function="steering.report.get",
        actor=ActorContext(actor_id="2", session_id=SESSION_ALPHA),
        target=TargetRef(kind="global"),
        payload=payload,
    )


def _held(test_db, monkeypatch):
    seed_standard_steering_world(test_db)
    with patch("yoke_core.domain.steering_claims.emit_steering_claimed"):
        acquire_steering(test_db, SESSION_ALPHA, PROJECT_ALPHA)
    _patch_report_dependencies(monkeypatch, test_db)


def test_composed_skipped_and_question_replies_are_labeled(test_db, monkeypatch):
    _held(test_db, monkeypatch)
    assert handle_get(_request()).telemetry == {"steering_report": "composed"}
    assert handle_get(_payload_request({"questions_only": True})).telemetry == {
        "steering_report": "questions_only"
    }
    monkeypatch.setattr(
        "yoke_core.domain.steering_fleet_report_delivery.claim_report_composition",
        lambda *_a, **_k: None,
    )
    skipped = handle_get(_payload_request({"deliver": True}))
    assert skipped.result_payload["composition_skipped"] is True
    assert skipped.telemetry == {"steering_report": "composition_skipped"}


def test_call_event_carries_the_handler_label(monkeypatch):
    from yoke_contracts.api.function_call import HandlerOutcome
    from yoke_core.domain import yoke_function_dispatch_events as events

    emitted = {}
    monkeypatch.setattr(
        events, "emit_event", lambda name, **kw: emitted.setdefault(name, kw)
    )
    request = _payload_request({})
    entry = type("Entry", (), {
        "function_id": "steering.report.get", "version": "v1", "side_effects": [],
        "claim_required_kind": None, "guardrails": [],
    })()
    response = type("Response", (), {"result": {}, "warnings": [], "error": None,
                                     "success": True})()
    events.emit_called(
        request, entry, HandlerOutcome(telemetry={"steering_report": "composed"}),
        response, 2, "hash", authorization_scope="scope",
        idempotency_payload_checksum="sum", claim_verification={},
    )
    context = emitted["YokeFunctionCalled"].get("context") or {}
    assert context.get("handler") == {"steering_report": "composed"}
