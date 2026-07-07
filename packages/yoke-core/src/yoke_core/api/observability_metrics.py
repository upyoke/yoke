"""Optional OpenTelemetry metric helpers for Yoke runtime code."""

from __future__ import annotations

from typing import Any, Mapping, Optional, Union


_COUNTERS: dict[str, Any] = {}
_HISTOGRAMS: dict[str, Any] = {}


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


def _clean_attributes(attributes: Optional[Mapping[str, Any]]) -> dict[str, Any]:
    return {
        key: value
        for key, value in (attributes or {}).items()
        if value is not None
    }
