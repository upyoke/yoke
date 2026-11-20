"""Each steering report reply names its path in the call's telemetry.

Latency acceptance measures full builds only, so the composed, skipped and
questions-only replies must be distinguishable in ``YokeFunctionCalled``.
"""

import sys
from unittest.mock import patch

import pytest

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
    assert handle_get(_request()).telemetry["steering_report"] == "composed"
    questions = handle_get(_payload_request({"questions_only": True}))
    assert questions.telemetry["steering_report"] == "questions_only"
    monkeypatch.setattr(
        "yoke_core.domain.steering_fleet_report_delivery.claim_report_composition",
        lambda *_a, **_k: None,
    )
    skipped = handle_get(_payload_request({"deliver": True}))
    assert skipped.result_payload["composition_skipped"] is True
    assert skipped.telemetry["steering_report"] == "composition_skipped"
    for reply in (questions, skipped):
        assert "steering_report_compose_cpu_ms" not in reply.telemetry


#: One Windows thread CPU clock tick (15.625ms), rounded up to whole ms.
WINDOWS_THREAD_CPU_TICK_MS = 16


def _ms(telemetry, key):
    suffix = "" if key == "statements" else "_ms"
    value = telemetry[f"steering_report_{key}{suffix}"]
    assert value.isdigit(), (key, value)
    return int(value)


def test_full_and_deliver_builds_carry_phase_timings(test_db, monkeypatch):
    _held(test_db, monkeypatch)
    full = handle_get(_request())
    assert full.telemetry["steering_report_build"] == "full"
    assert full.telemetry["steering_report_deliver"] == "false"
    assert _ms(full.telemetry, "statements") > 0
    for phase in ("connect", "claim", "compose", "render", "db"):
        assert _ms(full.telemetry, phase) <= _ms(full.telemetry, "wall"), phase
    # Thread CPU is a different clock from wall time. Windows advances it in
    # scheduler ticks of about 15.6ms (Python still reports 100ns resolution),
    # so a short build can show one tick of CPU over its wall time there.
    cpu_tick = WINDOWS_THREAD_CPU_TICK_MS if sys.platform == "win32" else 0
    assert _ms(full.telemetry, "cpu") <= _ms(full.telemetry, "wall") + cpu_tick
    assert "steering_report_record_ms" not in full.telemetry
    deliver = handle_get(_payload_request({"deliver": True}))
    assert deliver.telemetry["steering_report"] == "composed"
    assert deliver.telemetry["steering_report_build"] == "headline"
    assert deliver.telemetry["steering_report_deliver"] == "true"
    assert _ms(deliver.telemetry, "record") <= _ms(deliver.telemetry, "wall")
    for phase in ("compose_cpu", "compose_db", "compose_non_db_wait"):
        assert _ms(deliver.telemetry, phase) <= _ms(deliver.telemetry, "compose") + cpu_tick
    # Telemetry never reaches the reply.
    for reply in (full, deliver):
        assert not any(key.startswith("steering_report_") for key in reply.result_payload)


def test_delivery_counts_github_attempts_only_inside_compose(test_db, monkeypatch):
    from yoke_core.domain import gh_rest_transport as github
    from yoke_core.domain.handlers import steering_report
    from yoke_core.domain import steering_fleet_report_compose as compose
    from yoke_core.domain.steering_report_handler_timing import dependency_span

    _held(test_db, monkeypatch)
    monkeypatch.delenv("YOKE_REST_FAKE_DIR", raising=False)
    monkeypatch.setattr(github, "urlopen", lambda *_a, **_k: pytest.fail("live HTTP"))
    monkeypatch.setattr(github, "wait_before_retry", lambda *_a, **_k: None)
    responses = iter([
        github.RestNotFoundError("missing"),
        github.RestServerError("retry", status=503),
        github.RestResponse(200, {}, {}),
    ])

    def issue_once(*_args, **_kwargs):
        result = next(responses)
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(github, "_issue_once", issue_once)
    original = compose.compose_held_reports

    def compose_with_dependencies(*args, **kwargs):
        with dependency_span("lineage_contains"):
            with pytest.raises(github.RestNotFoundError):
                github.request_with_retry(
                    github.RestRequest("GET", "/repos/example/private"),
                    token="fixture-token",
                )
        github.request_with_retry(
            github.RestRequest("POST", "/graphql", replay_safe=True),
            token="fixture-token",
        )
        return original(*args, **kwargs)

    original_render = steering_report._render

    def render_with_dependency(*args, **kwargs):
        with dependency_span("outside_compose"):
            return original_render(*args, **kwargs)

    monkeypatch.setattr(compose, "compose_held_reports", compose_with_dependencies)
    monkeypatch.setattr(steering_report, "_render", render_with_dependency)
    reply = handle_get(_payload_request({"deliver": True}))
    assert reply.telemetry["steering_report"] == "composed"
    for dependency, count in (
        ("github_rest", "1"), ("github_graphql", "2"),
        ("github_retry_wait", "1"), ("lineage_contains", "1"),
    ):
        assert reply.telemetry[f"steering_report_compose_{dependency}_calls"] == count
        assert _ms(reply.telemetry, f"compose_{dependency}") <= _ms(reply.telemetry, "compose")
    assert "example/private" not in repr(reply.telemetry)
    assert "fixture-token" not in repr(reply.telemetry)
    assert not any("outside_compose" in key for key in reply.telemetry)


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
    handler = {
        "steering_report": "composed",
        "steering_report_compose_github_rest_calls": "2",
        "steering_report_compose_github_rest_ms": "1200",
    }
    events.emit_called(
        request, entry, HandlerOutcome(telemetry=handler),
        response, 2, "hash", authorization_scope="scope",
        idempotency_payload_checksum="sum", claim_verification={},
    )
    context = emitted["YokeFunctionCalled"].get("context") or {}
    assert context.get("handler") == handler
