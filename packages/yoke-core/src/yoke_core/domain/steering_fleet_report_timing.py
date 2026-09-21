"""Request-local steering timings, emitted through existing structured logs.

No SQL, event writes or report fields. Nested sections report inclusive wall
milliseconds; they overlap and must not be summed. GitHub sections include
credential resolution and retries, not just time on the network.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
from time import perf_counter
from typing import Any, Callable, Iterator

_LOG = logging.getLogger("yoke.api.steering_report")
_PHASES: ContextVar[dict[str, dict[str, Any]] | None] = ContextVar(
    "steering_report_phases", default=None
)


@contextmanager
def report_phase(name: str) -> Iterator[None]:
    """Measure one section only while an enclosing report is observed."""
    phases = _PHASES.get()
    if phases is None:
        yield
        return
    started = perf_counter()
    failed = True
    try:
        yield
        failed = False
    finally:
        phase = phases.setdefault(name, {"duration_ms": 0.0, "calls": 0, "errors": 0})
        phase["duration_ms"] += max(0.0, (perf_counter() - started) * 1000)
        phase["calls"] += 1
        phase["errors"] += int(failed)


def report_timed(name: str, *, root: bool = False) -> Callable:
    """Observe a report boundary or section without changing its result.

    A nested root shares its parent's collection. Each outer boundary logs
    once, including on failure, and always restores the caller's context.
    """

    def decorate(function: Callable) -> Callable:
        @wraps(function)
        def measured(*args: Any, **kwargs: Any) -> Any:
            if not root or _PHASES.get() is not None:
                with report_phase(name):
                    return function(*args, **kwargs)
            request = args[0] if name == "pull" and args else None
            actor = getattr(request, "actor", None)
            phases: dict[str, dict[str, Any]] = {}
            token = _PHASES.set(phases)
            outcome = "exception"
            try:
                with report_phase(name):
                    result = function(*args, **kwargs)
                outcome = "completed"
                return result
            finally:
                _PHASES.reset(token)
                try:
                    _LOG.info(
                        "steering_report.timing",
                        extra={
                            "event_name": "SteeringReportTiming",
                            "event_kind": "system",
                            "event_type": "diagnostic",
                            "session_id": kwargs.get("session_id")
                            or getattr(actor, "session_id", None),
                            "request_id": getattr(request, "request_id", None),
                            "function": getattr(request, "function", None),
                            "project_id": kwargs.get("project_id"),
                            "context": {
                                "operation": name,
                                "outcome": outcome,
                                "phases": {
                                    key: {
                                        **value,
                                        "duration_ms": round(value["duration_ms"], 3),
                                    }
                                    for key, value in phases.items()
                                },
                            },
                        },
                    )
                except Exception:
                    # Diagnostic delivery must never change report availability
                    # or replace the exception that the report itself raised.
                    pass

        return measured

    return decorate
