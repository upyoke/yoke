"""Optional OpenTelemetry metric helpers for Yoke runtime code."""

from __future__ import annotations

import os
import resource
import time
from typing import Any, Mapping, Optional, Union


_COUNTERS: dict[str, Any] = {}
_HISTOGRAMS: dict[str, Any] = {}
_PROCESS_CPU_BOUND = False
_CPU_SAMPLE: dict[str, float] = {}


def record_counter(
    name: str,
    *,
    value: int = 1,
    attributes: Optional[Mapping[str, Any]] = None,
) -> bool:
    """Record an OTel counter when metrics are available."""
    try:
        from opentelemetry import metrics
    except ImportError:
        return False
    try:
        counter = _COUNTERS.get(name)
        if counter is None:
            counter = metrics.get_meter("yoke.runtime").create_counter(name)
            _COUNTERS[name] = counter
        counter.add(value, attributes=_clean_attributes(attributes))
        return True
    except Exception:
        return False


def record_histogram(
    name: str,
    value: Union[int, float],
    *,
    attributes: Optional[Mapping[str, Any]] = None,
) -> bool:
    """Record an OTel histogram value when metrics are available."""
    try:
        from opentelemetry import metrics
    except ImportError:
        return False
    try:
        histogram = _HISTOGRAMS.get(name)
        if histogram is None:
            histogram = metrics.get_meter("yoke.runtime").create_histogram(name)
            _HISTOGRAMS[name] = histogram
        histogram.record(value, attributes=_clean_attributes(attributes))
        return True
    except Exception:
        return False


def bind_process_cpu_gauge() -> bool:
    """Register a process-CPU observable once a MeterProvider is exporting."""
    global _PROCESS_CPU_BOUND
    if _PROCESS_CPU_BOUND:
        return True
    try:
        from opentelemetry import metrics
        from opentelemetry.metrics import Observation
    except ImportError:
        return False
    try:
        _CPU_SAMPLE["wall"] = time.monotonic()
        _CPU_SAMPLE["cpu"] = _process_cpu_seconds()
        ncpu = float(os.cpu_count() or 1)

        def _observe(_options: Any) -> Any:
            now = time.monotonic()
            cpu = _process_cpu_seconds()
            dt = now - _CPU_SAMPLE["wall"]
            delta = cpu - _CPU_SAMPLE["cpu"]
            _CPU_SAMPLE["wall"] = now
            _CPU_SAMPLE["cpu"] = cpu
            percent = (delta / dt / ncpu) * 100.0 if dt > 0 else 0.0
            yield Observation(max(0.0, percent))

        metrics.get_meter("yoke.runtime").create_observable_gauge(
            "yoke.api.process.cpu.percent",
            callbacks=[_observe],
            unit="%",
            description="Serving process CPU as a percent of host capacity",
        )
        _PROCESS_CPU_BOUND = True
        return True
    except Exception:
        return False


def _process_cpu_seconds() -> float:
    usage = resource.getrusage(resource.RUSAGE_SELF)
    return float(usage.ru_utime + usage.ru_stime)


def _clean_attributes(attributes: Optional[Mapping[str, Any]]) -> dict[str, Any]:
    return {
        key: value for key, value in (attributes or {}).items() if value is not None
    }
