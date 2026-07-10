"""Tests for Yoke API observability helpers."""

from __future__ import annotations

import json
import logging
import sys

import pytest

from yoke_core.api import observability
from yoke_core.api import observability_otel


def test_json_log_formatter_emits_canonical_fields() -> None:
    record = logging.LogRecord(
        name="yoke.api.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=10,
        msg="request_complete",
        args=(),
        exc_info=None,
    )
    record.event_name = "HttpRequestCompleted"
    record.environment = "stage"
    record.actor_id = 7
    record.request_id = "req-1"
    record.context = {"status_code": 200}

    payload = json.loads(observability.JsonLogFormatter().format(record))

    assert payload["severity"] == "INFO"
    assert payload["message"] == "request_complete"
    assert payload["event_name"] == "HttpRequestCompleted"
    assert payload["environment"] == "stage"
    assert payload["actor_id"] == 7
    assert payload["request_id"] == "req-1"
    assert payload["context"]["status_code"] == 200


def test_new_request_id_preserves_header_or_generates_uuid() -> None:
    assert observability.new_request_id({"x-request-id": "req-fixed"}) == "req-fixed"
    generated = observability.new_request_id({})
    assert len(generated) == 36
    assert generated.count("-") == 4


def test_configure_otel_respects_explicit_disable() -> None:
    enabled, reason = observability.configure_otel(
        None,
        env={"YOKE_OTEL_DISABLED": "1"},
    )
    assert enabled is False
    assert reason == "disabled"


def test_otel_export_mode_resolves_configured_sink() -> None:
    mode = observability_otel._otel_export_mode
    assert mode({}) == "none"
    assert mode({"OTEL_EXPORTER_OTLP_ENDPOINT": "http://collector:4318"}) == "otlp"
    assert mode({"YOKE_OTEL_CONSOLE_EXPORT": "1"}) == "console"
    # Blank endpoint is not a sink.
    assert mode({"OTEL_EXPORTER_OTLP_ENDPOINT": "  "}) == "none"


def test_configure_otel_reason_is_honest_about_export() -> None:
    # No exporter endpoint configured: the reason must NOT claim a generic
    # "enabled" — either the dependency is absent (dev checkout) or the app
    # is instrumented but spans are dropped (no sink). Both are honest.
    enabled, reason = observability.configure_otel(None, env={})
    if reason.startswith("missing_dependency"):
        assert enabled is False
    else:
        assert enabled is True
        assert reason == "instrumented_no_exporter"
    # The misleading legacy "enabled" sentinel is gone.
    assert reason != "enabled"


def test_observation_span_is_safe_without_required_runtime() -> None:
    with observability.observation_span("yoke.test", {"yoke.value": "ok"}) as span:
        assert span is None or hasattr(span, "set_attribute")


def test_observation_span_no_otel_body_exception_chain_is_clean(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Field-note 12115: the no-op yield used to live inside the except
    # ImportError handler, so a body exception (e.g. UnknownProcessError
    # from a dispatched handler) printed with a "During handling of
    # ModuleNotFoundError: opentelemetry" context chain.
    monkeypatch.setitem(sys.modules, "opentelemetry", None)

    class SentinelError(Exception):
        pass

    with pytest.raises(SentinelError) as caught:
        with observability.observation_span("yoke.test") as span:
            assert span is None  # the no-op branch took effect
            raise SentinelError("body failure")

    assert not isinstance(caught.value.__context__, ImportError)
    assert caught.value.__context__ is None


def test_metric_helpers_are_safe_without_required_runtime() -> None:
    counter_result = observability.record_counter(
        "yoke.test.counter",
        attributes={"yoke.value": "ok"},
    )
    histogram_result = observability.record_histogram(
        "yoke.test.histogram",
        3,
        attributes={"yoke.value": "ok"},
    )
    assert counter_result in {True, False}
    assert histogram_result in {True, False}


def test_request_log_extra_uses_canonical_envelope_fields() -> None:
    extra = observability.request_log_extra(
        request_id="req-2",
        method="POST",
        path="/v1/functions/call",
        status_code=200,
        duration_ms=12,
        environment="stage",
        actor_id=3,
        token_id=4,
    )

    assert extra["event_name"] == "HttpRequestCompleted"
    assert extra["event_kind"] == "system"
    assert extra["event_type"] == "http_request"
    assert extra["service"] == "yoke-api"
    assert extra["environment"] == "stage"
    assert extra["actor_id"] == 3
    assert extra["request_id"] == "req-2"
    assert extra["context"]["api_token_id"] == 4
