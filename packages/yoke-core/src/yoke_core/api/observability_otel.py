"""OpenTelemetry setup for the Yoke API service (leaf module).

Split out of ``observability`` so the OTel wiring + service/environment
name resolution stays under the authored-file line cap. This module does
NOT import ``observability`` — ``observability`` re-exports these names so
existing callers keep importing from ``yoke_core.api.observability``.

The configured sink is resolved once via :func:`_otel_export_mode`. With
no exporter endpoint set, the app is instrumented but spans are created
and dropped and no metric provider is installed — the CloudWatch
structured logs are the live observability surface in that mode.
"""

from __future__ import annotations

import os
from typing import Any, Mapping, Optional


DEFAULT_SERVICE_NAME = "yoke-api"
DEFAULT_ENVIRONMENT = "development"

_OTEL_APP_MARKER = "_yoke_otel_instrumented"


def service_name(env: Optional[Mapping[str, str]] = None) -> str:
    source = os.environ if env is None else env
    return (
        source.get("YOKE_OTEL_SERVICE_NAME")
        or source.get("YOKE_SERVICE_NAME")
        or DEFAULT_SERVICE_NAME
    )


def environment_name(env: Optional[Mapping[str, str]] = None) -> str:
    source = os.environ if env is None else env
    return (
        source.get("YOKE_ENVIRONMENT")
        or source.get("APP_ENV")
        or DEFAULT_ENVIRONMENT
    )


def configure_otel(
    app: Any = None,
    *,
    env: Optional[Mapping[str, str]] = None,
) -> tuple[bool, str]:
    """Wire OTel when installed; degrade cleanly in local dev checkouts.

    The returned reason is honest about whether spans/metrics actually
    leave the process: ``exporting:otlp`` / ``exporting:console`` when a
    sink is configured, ``instrumented_no_exporter`` when the app is
    instrumented but no exporter endpoint is set (spans created and
    dropped), ``disabled``, or ``missing_dependency:<pkg>``.
    """
    source = os.environ if env is None else env
    if str(source.get("YOKE_OTEL_DISABLED", "")).lower() in {"1", "true", "yes"}:
        return False, "disabled"
    try:
        from opentelemetry import metrics, trace
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        from opentelemetry.sdk.metrics import MeterProvider
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
    except ImportError as exc:
        return False, f"missing_dependency:{exc.name or 'opentelemetry'}"

    mode = _otel_export_mode(source)
    resource = Resource.create(
        {
            "service.name": service_name(source),
            "deployment.environment": environment_name(source),
        }
    )
    try:
        tracer_provider = TracerProvider(resource=resource)
        exporter = _span_exporter(source)
        if exporter is not None:
            tracer_provider.add_span_processor(BatchSpanProcessor(exporter))
        trace.set_tracer_provider(tracer_provider)
    except Exception as exc:  # noqa: BLE001 - OTel setup must not block startup
        return False, f"trace_setup_failed:{type(exc).__name__}"

    # Only install an exporting MeterProvider when a sink exists. A bare
    # MeterProvider() with no metric reader is a black hole that implies
    # metrics work — leave the default no-op provider when nothing exports.
    try:
        reader = _metric_reader(source)
        if reader is not None:
            metrics.set_meter_provider(
                MeterProvider(resource=resource, metric_readers=[reader])
            )
    except Exception:  # noqa: BLE001 - metric setup must not block startup
        pass

    if app is not None and not getattr(app, _OTEL_APP_MARKER, False):
        try:
            FastAPIInstrumentor.instrument_app(app, tracer_provider=tracer_provider)
            setattr(app, _OTEL_APP_MARKER, True)
        except Exception as exc:  # noqa: BLE001
            return False, f"fastapi_instrumentation_failed:{type(exc).__name__}"
    if mode == "otlp":
        return True, "exporting:otlp"
    if mode == "console":
        return True, "exporting:console"
    return True, "instrumented_no_exporter"


def _otel_export_mode(env: Mapping[str, str]) -> str:
    """Resolve the configured OTel sink: ``otlp`` | ``console`` | ``none``."""
    if str(env.get("OTEL_EXPORTER_OTLP_ENDPOINT") or "").strip():
        return "otlp"
    if str(env.get("YOKE_OTEL_CONSOLE_EXPORT", "")).lower() in {"1", "true", "yes"}:
        return "console"
    return "none"


def _span_exporter(env: Mapping[str, str]) -> Any:
    mode = _otel_export_mode(env)
    if mode == "otlp":
        try:
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
                OTLPSpanExporter,
            )
            return OTLPSpanExporter()
        except ImportError:
            return None
    if mode == "console":
        from opentelemetry.sdk.trace.export import ConsoleSpanExporter

        return ConsoleSpanExporter()
    return None


def _metric_reader(env: Mapping[str, str]) -> Any:
    """Build a periodic metric reader matching the configured sink, or None."""
    mode = _otel_export_mode(env)
    if mode == "otlp":
        try:
            from opentelemetry.exporter.otlp.proto.http.metric_exporter import (
                OTLPMetricExporter,
            )
            from opentelemetry.sdk.metrics.export import (
                PeriodicExportingMetricReader,
            )
            return PeriodicExportingMetricReader(OTLPMetricExporter())
        except ImportError:
            return None
    if mode == "console":
        try:
            from opentelemetry.sdk.metrics.export import (
                ConsoleMetricExporter,
                PeriodicExportingMetricReader,
            )
            return PeriodicExportingMetricReader(ConsoleMetricExporter())
        except ImportError:
            return None
    return None


__all__ = [
    "DEFAULT_ENVIRONMENT",
    "DEFAULT_SERVICE_NAME",
    "configure_otel",
    "environment_name",
    "service_name",
]
