"""Observability wrapper for Yoke function dispatch."""

from __future__ import annotations

import time
from contextlib import contextmanager
from typing import Any, Dict, Iterator

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionCallResponse,
)
from yoke_core.api.observability import (
    now_ms,
    observation_span,
    record_counter,
    record_histogram,
)


@contextmanager
def dispatch_observation(request: Any) -> Iterator[Any]:
    started = time.perf_counter()
    attributes = _span_attributes(request)
    state = {"outcome": "exception"}

    def mark(response: FunctionCallResponse) -> None:
        state["outcome"] = "success" if response.success else "error"

    try:
        with observation_span("yoke.function.dispatch", attributes):
            yield mark
    finally:
        metric_attributes = dict(attributes)
        metric_attributes["yoke.outcome"] = state["outcome"]
        record_counter(
            "yoke.function.dispatch.calls",
            attributes=metric_attributes,
        )
        record_histogram(
            "yoke.function.dispatch.duration_ms",
            now_ms(started),
            attributes=metric_attributes,
        )


def _span_attributes(request: Any) -> Dict[str, Any]:
    if isinstance(request, FunctionCallRequest):
        return {
            "yoke.function": request.function,
            "yoke.function_version": request.version,
            "yoke.request_id": request.request_id,
        }
    if isinstance(request, dict):
        return {
            "yoke.function": request.get("function"),
            "yoke.function_version": request.get("version") or "v1",
            "yoke.request_id": request.get("request_id"),
        }
    return {"yoke.function": type(request).__name__}
