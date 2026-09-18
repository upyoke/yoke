"""Observability wrapper for Yoke function dispatch."""

from __future__ import annotations

import logging
import time
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Dict, Iterator

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionCallResponse,
)
from yoke_core.api.observability import (
    observation_span,
    record_counter,
    record_histogram,
    service_name,
)

_DISPATCH_DEBUG_LOG = logging.getLogger("yoke.api.dispatch")

_METRIC_SPAN_KEYS = ("yoke.function", "yoke.function_version")

#: Handler duration of the dispatch running in this context, for the caller
#: that wants the dispatcher's overhead rather than the handler's own time.
_HANDLER_DURATION_MS: ContextVar[int | None] = ContextVar(
    "yoke_dispatch_handler_duration_ms", default=None
)


def _read_monotonic() -> float:
    return time.monotonic()


def start_duration_measurement() -> float | None:
    """Return a monotonic start marker without disrupting the caller."""
    try:
        return _read_monotonic()
    except Exception:
        return None


def elapsed_duration_ms(started: float | None) -> int | None:
    """Return non-negative elapsed milliseconds, or ``None`` if unavailable."""
    if started is None:
        return None
    finished = start_duration_measurement()
    if finished is None:
        return None
    return max(0, int((finished - started) * 1000))


def note_handler_duration(duration_ms: int | None) -> None:
    """Publish the handler's own duration for the dispatch running here."""
    _HANDLER_DURATION_MS.set(duration_ms)


def handler_duration_ms() -> int | None:
    """Return the handler duration of the dispatch that just returned here.

    ``YokeFunctionCalled`` reports only the handler, so a caller that timed
    the whole dispatch subtracts this to see the dispatcher's own overhead —
    envelope coercion, registry lookup, permission and claim checks, and
    response building — as a number instead of an unexplained remainder.
    """
    return _HANDLER_DURATION_MS.get()


@contextmanager
def dispatch_observation(request: Any) -> Iterator[Any]:
    started = start_duration_measurement()
    # Clear first: an unmeasured or short-circuited dispatch must not let the
    # previous call's handler duration be read as this one's.
    note_handler_duration(None)
    span_attributes = _span_attributes(request)
    state = {"outcome": "exception"}

    def mark(response: FunctionCallResponse) -> None:
        state["outcome"] = "success" if response.success else "error"

    try:
        with observation_span("yoke.function.dispatch", span_attributes):
            _emit_scoped_debug(request, span_attributes)
            yield mark
    finally:
        metric_attributes = _metric_attributes(span_attributes, state["outcome"])
        record_counter(
            "yoke.function.dispatch.calls",
            attributes=metric_attributes,
        )
        duration_ms = elapsed_duration_ms(started)
        if duration_ms is not None:
            record_histogram(
                "yoke.function.dispatch.duration_ms",
                duration_ms,
                attributes=metric_attributes,
            )


def _emit_scoped_debug(request: Any, span_attributes: Dict[str, Any]) -> None:
    """Emit one DEBUG log for an in-scope campaign; the filter enforces expiry."""
    actor = getattr(request, "actor", None)
    session_id = getattr(actor, "session_id", None) if actor is not None else None
    if session_id is None and isinstance(request, dict):
        nested = request.get("actor") or {}
        session_id = nested.get("session_id") if isinstance(nested, dict) else None
    _DISPATCH_DEBUG_LOG.debug(
        "dispatch.debug",
        extra={
            "event_name": "FunctionDispatchDebug",
            "event_kind": "system",
            "event_type": "function_call",
            "function": span_attributes.get("yoke.function"),
            "request_id": span_attributes.get("yoke.request_id"),
            "session_id": session_id,
            "service": service_name(),
        },
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


def _metric_attributes(span_attributes: Dict[str, Any], outcome: str) -> Dict[str, Any]:
    attributes = {
        key: span_attributes[key]
        for key in _METRIC_SPAN_KEYS
        if span_attributes.get(key) is not None
    }
    attributes["yoke.outcome"] = outcome
    return attributes
