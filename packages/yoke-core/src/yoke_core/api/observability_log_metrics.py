"""CloudWatch Embedded Metric Format export for hosted API metrics.

When no OTLP collector is configured, hosted API processes still need a
meter provider so ``record_histogram`` / ``record_counter`` and the
process-CPU gauge actually leave the box. This module turns an OTel
``MetricsData`` batch into EMF JSON lines on ``yoke.api.metrics`` (stderr
→ the existing CloudWatch log group).
"""

from __future__ import annotations

import json
import logging
import sys
import time
from typing import Any


EMF_NAMESPACE = "Yoke/API"
EMF_LOGGER_NAME = "yoke.api.metrics"
_EXPORT_INTERVAL_MS = 60_000


def emf_documents(
    metrics_data: Any,
    *,
    namespace: str = EMF_NAMESPACE,
) -> list[dict[str, Any]]:
    """Walk an OTel ``MetricsData`` batch into one EMF document per point."""
    docs: list[dict[str, Any]] = []
    for resource_metrics in getattr(metrics_data, "resource_metrics", None) or ():
        environment = _resource_environment(getattr(resource_metrics, "resource", None))
        for scope_metrics in getattr(resource_metrics, "scope_metrics", None) or ():
            for metric in getattr(scope_metrics, "metrics", None) or ():
                docs.extend(
                    _metric_documents(
                        metric, namespace=namespace, environment=environment
                    )
                )
    return docs


def make_log_metric_reader() -> Any:
    """Periodic reader that writes EMF JSON to the metrics logger."""
    from opentelemetry.sdk.metrics.export import (
        MetricExportResult,
        MetricExporter,
        PeriodicExportingMetricReader,
    )

    logger = _configure_emf_logger()

    class _EmfExporter(MetricExporter):
        def export(
            self,
            metrics_data: Any,
            timeout_millis: float = 10_000,
            **kwargs: Any,
        ) -> MetricExportResult:
            del timeout_millis, kwargs
            try:
                for document in emf_documents(metrics_data):
                    logger.info("%s", json.dumps(document, separators=(",", ":")))
            except Exception:
                return MetricExportResult.FAILURE
            return MetricExportResult.SUCCESS

        def shutdown(self, timeout_millis: float = 30_000, **kwargs: Any) -> None:
            del timeout_millis, kwargs
            return None

        def force_flush(self, timeout_millis: float = 10_000) -> bool:
            del timeout_millis
            return True

    return PeriodicExportingMetricReader(
        _EmfExporter(),
        export_interval_millis=_EXPORT_INTERVAL_MS,
    )


def _configure_emf_logger() -> logging.Logger:
    """Raw-JSON stderr so CloudWatch EMF is not wrapped by JsonLogFormatter."""
    logger = logging.getLogger(EMF_LOGGER_NAME)
    logger.propagate = False
    if not any(isinstance(handler, _RawStderrHandler) for handler in logger.handlers):
        handler = _RawStderrHandler(sys.stderr)
        handler.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    return logger


class _RawStderrHandler(logging.StreamHandler):
    """Marker handler so the EMF logger is configured once."""


def _resource_environment(resource: Any) -> str:
    attributes = getattr(resource, "attributes", None) or {}
    value = attributes.get("deployment.environment")
    return str(value) if value else ""


def _metric_documents(
    metric: Any,
    *,
    namespace: str,
    environment: str,
) -> list[dict[str, Any]]:
    name = getattr(metric, "name", "") or ""
    data = getattr(metric, "data", None)
    points = getattr(data, "data_points", None) or ()
    documents: list[dict[str, Any]] = []
    for point in points:
        samples = _numeric_samples(name, point)
        if not samples:
            continue
        body: dict[str, Any] = {}
        if environment:
            body["Environment"] = environment
        for key, value in dict(getattr(point, "attributes", None) or {}).items():
            if value is not None:
                body[str(key)] = value
        metric_defs = []
        for sample_name, sample_value, unit in samples:
            body[sample_name] = sample_value
            metric_defs.append({"Name": sample_name, "Unit": unit})
        body["_aws"] = {
            "Timestamp": _timestamp_ms(point),
            "CloudWatchMetrics": [
                {
                    "Namespace": namespace,
                    "Dimensions": [["Environment"]] if environment else [],
                    "Metrics": metric_defs,
                }
            ],
        }
        documents.append(body)
    return documents


def _numeric_samples(name: str, point: Any) -> list[tuple[str, float, str]]:
    if hasattr(point, "count") and hasattr(point, "sum"):
        return [
            (f"{name}.sum", float(point.sum or 0), "None"),
            (f"{name}.count", float(point.count or 0), "Count"),
            (f"{name}.max", float(getattr(point, "max", 0) or 0), "None"),
        ]
    value = getattr(point, "value", None)
    if value is None:
        return []
    unit = "Percent" if name.endswith("cpu.percent") else "None"
    return [(name, float(value), unit)]


def _timestamp_ms(point: Any) -> int:
    nanos = getattr(point, "time_unix_nano", None)
    if isinstance(nanos, int) and nanos > 0:
        return nanos // 1_000_000
    return int(time.time() * 1000)


def log_metrics_requested(env: Any) -> bool:
    """True when hosted (or an explicit flag) should install the log sink."""
    flag = str(env.get("YOKE_OTEL_LOG_METRICS", "")).lower()
    if flag in {"0", "false", "no"}:
        return False
    if flag in {"1", "true", "yes"}:
        return True
    environment = env.get("YOKE_ENVIRONMENT") or env.get("APP_ENV") or ""
    return environment in {"prod", "stage"}


__all__ = [
    "EMF_LOGGER_NAME",
    "EMF_NAMESPACE",
    "emf_documents",
    "log_metrics_requested",
    "make_log_metric_reader",
]
