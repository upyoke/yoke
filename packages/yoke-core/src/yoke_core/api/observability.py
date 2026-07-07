"""Runtime observability helpers for the Yoke API service.

Yoke owns the semantic event envelope. This module owns service/runtime
visibility around that envelope: structured stdout logs, request ids, and
optional OpenTelemetry instrumentation when the packages and exporter config
are present.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping, Optional

from yoke_core.api.observability_metrics import record_counter, record_histogram
from yoke_core.api.observability_otel import (
    configure_otel,
    environment_name,
    service_name,
)


REQUEST_ID_HEADER = "x-request-id"
REQUEST_ID_STATE_ATTR = "yoke_request_id"

_JSON_HANDLER_MARKER = "_yoke_json_stdout_handler"

CANONICAL_LOG_FIELDS = (
    "event_name",
    "event_kind",
    "event_type",
    "severity",
    "service",
    "environment",
    "org_id",
    "project",
    "project_id",
    "user_id",
    "actor_id",
    "session_id",
    "request_id",
    "item_id",
    "task_num",
    "trace_id",
    "span_id",
    "parent_id",
    "context",
)


@dataclass(frozen=True)
class ObservabilitySetup:
    """Structured result for startup observability setup."""

    structured_logging: bool
    otel_enabled: bool
    otel_reason: str = ""


class JsonLogFormatter(logging.Formatter):
    """Emit newline-delimited JSON suitable for Docker and CloudWatch Logs."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "severity": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for field in CANONICAL_LOG_FIELDS:
            if hasattr(record, field):
                value = getattr(record, field)
                if value is not None:
                    payload[field] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, separators=(",", ":"), default=str)


def configure_structured_logging(
    *,
    level: str = "INFO",
    stream: Any = None,
) -> None:
    """Configure root logging for structured stdout emission."""
    target = sys.stdout if stream is None else stream
    root = logging.getLogger()
    normalized_level = getattr(logging, str(level).upper(), logging.INFO)
    root.setLevel(normalized_level)

    for handler in root.handlers:
        if getattr(handler, _JSON_HANDLER_MARKER, False):
            handler.setLevel(normalized_level)
            handler.setFormatter(JsonLogFormatter())
            return

    handler = logging.StreamHandler(target)
    setattr(handler, _JSON_HANDLER_MARKER, True)
    handler.setLevel(normalized_level)
    handler.setFormatter(JsonLogFormatter())
    root.addHandler(handler)


def configure_observability(
    app: Any = None,
    *,
    env: Optional[Mapping[str, str]] = None,
    log_level: str = "INFO",
) -> ObservabilitySetup:
    """Configure structured logs and optional OpenTelemetry instrumentation."""
    source = os.environ if env is None else env
    configure_structured_logging(level=log_level)
    otel_enabled, otel_reason = configure_otel(app, env=source)
    return ObservabilitySetup(
        structured_logging=True,
        otel_enabled=otel_enabled,
        otel_reason=otel_reason,
    )


def new_request_id(headers: Mapping[str, str]) -> str:
    """Return caller-provided request id or generate a fresh one."""
    existing = headers.get(REQUEST_ID_HEADER) or headers.get(REQUEST_ID_HEADER.title())
    if existing and str(existing).strip():
        return str(existing).strip()
    return str(uuid.uuid4())


def trace_context() -> dict[str, str]:
    """Return current OTel trace/span identifiers when available."""
    try:
        from opentelemetry import trace
    except ImportError:
        return {}
    try:
        span = trace.get_current_span()
        context = span.get_span_context()
    except Exception:
        return {}
    if not getattr(context, "is_valid", False):
        return {}
    return {
        "trace_id": f"{context.trace_id:032x}",
        "span_id": f"{context.span_id:016x}",
    }


@contextmanager
def observation_span(
    name: str,
    attributes: Optional[Mapping[str, Any]] = None,
) -> Iterator[Any]:
    """Start an OTel span when available; otherwise behave as a no-op."""
    try:
        from opentelemetry import trace
    except ImportError:
        trace = None
    if trace is None:
        # No-op yield happens OUTSIDE the except handler so a body
        # exception does not chain (__context__) to the ImportError and
        # mislead diagnosis toward OTel.
        yield None
        return
    tracer = trace.get_tracer("yoke.runtime")
    with tracer.start_as_current_span(name) as span:
        for key, value in (attributes or {}).items():
            if value is not None:
                span.set_attribute(key, value)
        yield span


def now_ms(start: float) -> int:
    return max(0, int((time.perf_counter() - start) * 1000))


def request_log_extra(
    *,
    request_id: str,
    method: str,
    path: str,
    status_code: int,
    duration_ms: int,
    environment: str,
    actor_id: Optional[int] = None,
    token_id: Optional[int] = None,
    outcome: str = "completed",
) -> dict[str, Any]:
    context = {
        "method": method,
        "path": path,
        "status_code": status_code,
        "duration_ms": duration_ms,
        "outcome": outcome,
    }
    if token_id is not None:
        context["api_token_id"] = token_id
    extra: dict[str, Any] = {
        "event_name": "HttpRequestCompleted",
        "event_kind": "system",
        "event_type": "http_request",
        "severity": "INFO" if status_code < 500 else "ERROR",
        "service": service_name(),
        "environment": environment,
        "actor_id": actor_id,
        "request_id": request_id,
        "context": context,
    }
    extra.update(trace_context())
    return extra


__all__ = [
    "JsonLogFormatter",
    "ObservabilitySetup",
    "REQUEST_ID_HEADER",
    "REQUEST_ID_STATE_ATTR",
    "configure_observability",
    "configure_otel",
    "configure_structured_logging",
    "environment_name",
    "new_request_id",
    "now_ms",
    "observation_span",
    "record_counter",
    "record_histogram",
    "request_log_extra",
    "service_name",
    "trace_context",
]
