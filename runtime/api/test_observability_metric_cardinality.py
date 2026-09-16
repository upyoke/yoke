"""Bounded metric series and delta EMF export for hosted API metrics."""

from __future__ import annotations

import json
import logging
from types import SimpleNamespace
from typing import Any

import pytest
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    FunctionCallResponse,
    TargetRef,
)
from yoke_core.api.observability_log_metrics import (
    EMF_LOGGER_NAME,
    emf_documents,
    make_log_metric_reader,
)
from yoke_core.api.observability_metrics import metric_attributes
from yoke_core.domain.yoke_function_dispatch_observability import dispatch_observation


def _request(request_id: str, function: str = "items.get.run") -> FunctionCallRequest:
    return FunctionCallRequest(
        function=function,
        actor=ActorContext(actor_id="2", session_id="metric-session"),
        target=TargetRef(kind="item", item_id=42),
        request_id=request_id,
    )


def _ok(function: str = "items.get.run") -> FunctionCallResponse:
    return FunctionCallResponse(success=True, function=function, version="v1")


def test_metric_attributes_drop_correlation_ids() -> None:
    cleaned = metric_attributes(
        {
            "yoke.function": "items.get.run",
            "yoke.outcome": "success",
            "yoke.request_id": "req-1",
            "session_id": "sess-1",
            "trace_id": "abc",
            "http_request_id": "http-1",
            "empty": None,
        }
    )
    assert cleaned == {
        "yoke.function": "items.get.run",
        "yoke.outcome": "success",
    }


def test_dispatch_metrics_omit_request_id_as_ids_grow(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[dict[str, Any]] = []

    def _capture(name: str, *, attributes=None, value: int = 1) -> bool:
        del name, value
        captured.append(dict(attributes or {}))
        return True

    monkeypatch.setattr(
        "yoke_core.domain.yoke_function_dispatch_observability.record_counter",
        _capture,
    )
    monkeypatch.setattr(
        "yoke_core.domain.yoke_function_dispatch_observability.record_histogram",
        lambda *args, **kwargs: True,
    )
    seen_span_ids: list[Any] = []

    def _span(name: str, attributes=None):
        del name
        seen_span_ids.append((attributes or {}).get("yoke.request_id"))
        from contextlib import nullcontext

        return nullcontext()

    monkeypatch.setattr(
        "yoke_core.domain.yoke_function_dispatch_observability.observation_span",
        _span,
    )

    for index in range(40):
        with dispatch_observation(_request(f"req-{index}")) as mark:
            mark(_ok())

    series = {tuple(sorted(row.items())) for row in captured}
    assert len(series) == 1
    assert captured[0] == {
        "yoke.function": "items.get.run",
        "yoke.function_version": "v1",
        "yoke.outcome": "success",
    }
    assert "yoke.request_id" not in captured[0]
    assert seen_span_ids == [f"req-{index}" for index in range(40)]


def test_emf_documents_keep_environment_dimension_without_request_ids() -> None:
    point = SimpleNamespace(
        attributes={
            "yoke.function": "items.get.run",
            "yoke.outcome": "success",
            "yoke.request_id": "req-explode",
        },
        value=4.0,
        time_unix_nano=1_700_000_000_000_000_000,
    )
    metrics_data = SimpleNamespace(
        resource_metrics=[
            SimpleNamespace(
                resource=SimpleNamespace(
                    attributes={"deployment.environment": "prod"}
                ),
                scope_metrics=[
                    SimpleNamespace(
                        metrics=[
                            SimpleNamespace(
                                name="yoke.function.dispatch.calls",
                                data=SimpleNamespace(data_points=[point]),
                            )
                        ]
                    )
                ],
            )
        ]
    )
    docs = emf_documents(metrics_data)
    assert len(docs) == 1
    body = docs[0]
    assert body["Environment"] == "prod"
    assert body["yoke.function"] == "items.get.run"
    assert "yoke.request_id" not in body
    assert body["_aws"]["CloudWatchMetrics"][0]["Dimensions"] == [["Environment"]]


def test_emf_reader_prefers_delta_for_counters_and_histograms() -> None:
    pytest.importorskip("opentelemetry.sdk")
    from opentelemetry.sdk.metrics import Counter, Histogram, ObservableGauge
    from opentelemetry.sdk.metrics.export import AggregationTemporality

    reader = make_log_metric_reader()
    try:
        preferred = reader._exporter._preferred_temporality
        assert preferred[Counter] == AggregationTemporality.DELTA
        assert preferred[Histogram] == AggregationTemporality.DELTA
        assert ObservableGauge not in preferred
    finally:
        reader.shutdown()


def _capture_emf() -> tuple[list[dict[str, Any]], logging.Handler]:
    captured: list[dict[str, Any]] = []

    class _Handler(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            captured.append(json.loads(record.getMessage()))

    handler = _Handler()
    logger = logging.getLogger(EMF_LOGGER_NAME)
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    return captured, handler


def test_delta_export_does_not_recount_old_requests() -> None:
    pytest.importorskip("opentelemetry.sdk")
    from opentelemetry.sdk.metrics import MeterProvider

    captured, handler = _capture_emf()
    logger = logging.getLogger(EMF_LOGGER_NAME)
    reader = make_log_metric_reader()
    provider = MeterProvider(metric_readers=[reader])
    meter = provider.get_meter("yoke.test.delta")
    counter = meter.create_counter("yoke.function.dispatch.calls")
    histogram = meter.create_histogram("yoke.function.dispatch.duration_ms")
    attrs = {"yoke.function": "items.get.run", "yoke.outcome": "success"}
    try:
        for _ in range(5):
            counter.add(1, attributes=attrs)
            histogram.record(10, attributes=attrs)
        assert provider.force_flush()
        first = list(captured)
        captured.clear()

        counter.add(1, attributes=attrs)
        histogram.record(40, attributes=attrs)
        assert provider.force_flush()
        second = list(captured)
        captured.clear()
    finally:
        provider.shutdown()
        logger.removeHandler(handler)

    first_count = [doc for doc in first if "yoke.function.dispatch.calls" in doc]
    second_count = [doc for doc in second if "yoke.function.dispatch.calls" in doc]
    first_hist = [
        doc for doc in first if "yoke.function.dispatch.duration_ms.count" in doc
    ]
    second_hist = [
        doc for doc in second if "yoke.function.dispatch.duration_ms.count" in doc
    ]
    assert first_count[0]["yoke.function.dispatch.calls"] == 5.0
    assert second_count[0]["yoke.function.dispatch.calls"] == 1.0
    assert first_hist[0]["yoke.function.dispatch.duration_ms.count"] == 5.0
    assert first_hist[0]["yoke.function.dispatch.duration_ms.sum"] == 50.0
    assert second_hist[0]["yoke.function.dispatch.duration_ms.count"] == 1.0
    assert second_hist[0]["yoke.function.dispatch.duration_ms.sum"] == 40.0


def test_new_meter_provider_starts_counts_from_zero() -> None:
    pytest.importorskip("opentelemetry.sdk")
    from opentelemetry.sdk.metrics import MeterProvider

    captured, handler = _capture_emf()
    logger = logging.getLogger(EMF_LOGGER_NAME)
    attrs = {"yoke.function": "items.get.run", "yoke.outcome": "success"}
    try:
        first_reader = make_log_metric_reader()
        first_provider = MeterProvider(metric_readers=[first_reader])
        first_provider.get_meter("yoke.test.reset").create_counter(
            "yoke.function.dispatch.calls"
        ).add(3, attributes=attrs)
        first_provider.force_flush()
        first_provider.shutdown()
        captured.clear()

        second_reader = make_log_metric_reader()
        second_provider = MeterProvider(metric_readers=[second_reader])
        second_provider.get_meter("yoke.test.reset").create_counter(
            "yoke.function.dispatch.calls"
        ).add(1, attributes=attrs)
        second_provider.force_flush()
        second = [doc for doc in captured if "yoke.function.dispatch.calls" in doc]
        second_provider.shutdown()
    finally:
        logger.removeHandler(handler)

    assert second[0]["yoke.function.dispatch.calls"] == 1.0


def test_live_export_cardinality_stays_bounded_as_request_ids_grow() -> None:
    pytest.importorskip("opentelemetry.sdk")
    from opentelemetry.sdk.metrics import MeterProvider

    captured, handler = _capture_emf()
    logger = logging.getLogger(EMF_LOGGER_NAME)
    reader = make_log_metric_reader()
    provider = MeterProvider(metric_readers=[reader])
    meter = provider.get_meter("yoke.test.card")
    counter = meter.create_counter("yoke.function.dispatch.calls")
    try:
        for index in range(25):
            counter.add(
                1,
                attributes=metric_attributes(
                    {
                        "yoke.function": "items.get.run",
                        "yoke.outcome": "success",
                        "yoke.request_id": f"req-{index}",
                    }
                ),
            )
        provider.force_flush()
        call_docs = [
            doc for doc in captured if "yoke.function.dispatch.calls" in doc
        ]
    finally:
        provider.shutdown()
        logger.removeHandler(handler)

    assert len(call_docs) == 1
    assert call_docs[0]["yoke.function.dispatch.calls"] == 25.0
    assert "yoke.request_id" not in call_docs[0]
