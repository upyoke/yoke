"""Where one steering report request spends its time, as call telemetry.

The handler's served duration is the only latency Production records, and
measured from outside it hides which part dominates: the database answers a
statement in a fraction of a millisecond and a build issues a few hundred, yet
served builds take seconds. These timings split one request into its phases,
count its statements and the time spent inside them, and give the thread's own
CPU. Composition additionally records the observed dependency calls and an
estimate of wait outside measured SQL.

Telemetry only: the values ride on the call event's handler context and no
code reads them back.
"""

from __future__ import annotations

from collections import Counter
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
from time import perf_counter, thread_time
from typing import Any, Dict, Iterator

PREFIX = "steering_report_"
_COMPOSITION: ContextVar["HandlerTiming | None"] = ContextVar(
    "steering_report_composition", default=None
)


@contextmanager
def dependency_span(name: str) -> Iterator[None]:
    """Accumulate elapsed time and calls only within the composing request."""
    timing = _COMPOSITION.get()
    if timing is None:
        yield
        return
    started = perf_counter()
    try:
        yield
    finally:
        timing.dependency_seconds[name] += perf_counter() - started
        timing.dependency_calls[name] += 1


def time_dependency(name: str):
    def decorate(function):
        @wraps(function)
        def run(*args, **kwargs):
            with dependency_span(name):
                return function(*args, **kwargs)

        return run

    return decorate


class _CountedConnection:
    """Delegates everything; counts statements and the time spent in them."""

    def __init__(self, conn: Any, timing: "HandlerTiming"):
        self._inner = conn
        self._timing = timing

    def __getattr__(self, name):
        return getattr(self._inner, name)

    def execute(self, *args, **kwargs):
        started = perf_counter()
        try:
            return self._inner.execute(*args, **kwargs)
        finally:
            self._timing.statements += 1
            self._timing.db_seconds += perf_counter() - started


class HandlerTiming:
    """Phase wall times, statement count, DB time and thread CPU for one call."""

    def __init__(self) -> None:
        self._wall = perf_counter()
        self._cpu = thread_time()
        self.phases: Dict[str, float] = {}
        self.statements = 0
        self.db_seconds = 0.0
        self.compose_cpu_seconds = 0.0
        self.compose_db_seconds = 0.0
        self.dependency_calls: Counter[str] = Counter()
        self.dependency_seconds: Counter[str] = Counter()

    def counted(self, conn: Any) -> Any:
        return _CountedConnection(conn, self)

    @contextmanager
    def phase(self, name: str) -> Iterator[None]:
        started = perf_counter()
        try:
            yield
        finally:
            self.phases[name] = self.phases.get(name, 0.0) + perf_counter() - started

    @contextmanager
    def composition(self) -> Iterator[None]:
        cpu = thread_time()
        db = self.db_seconds
        token = _COMPOSITION.set(self)
        try:
            with self.phase("compose"):
                yield
        finally:
            _COMPOSITION.reset(token)
            self.compose_cpu_seconds += thread_time() - cpu
            self.compose_db_seconds += self.db_seconds - db

    def telemetry(self, *, build: str, deliver: bool) -> Dict[str, str]:
        """Flat string values for the call event's handler context.

        ``build`` is ``full`` when the reply composed the inventory sections
        and ``headline`` when it did not; ``deliver`` marks the fleet
        watcher's delivery calls.
        """

        def ms(seconds: float) -> str:
            return str(round(seconds * 1000))

        values = {
            f"{PREFIX}build": build,
            f"{PREFIX}deliver": "true" if deliver else "false",
            f"{PREFIX}wall_ms": ms(perf_counter() - self._wall),
            f"{PREFIX}cpu_ms": ms(thread_time() - self._cpu),
            f"{PREFIX}db_ms": ms(self.db_seconds),
            f"{PREFIX}statements": str(self.statements),
        }
        for name, seconds in self.phases.items():
            values[f"{PREFIX}{name}_ms"] = ms(seconds)
        if "compose" in self.phases:
            values[f"{PREFIX}compose_cpu_ms"] = ms(self.compose_cpu_seconds)
            values[f"{PREFIX}compose_db_ms"] = ms(self.compose_db_seconds)
            values[f"{PREFIX}compose_non_db_wait_ms"] = ms(max(
                0.0,
                self.phases["compose"] - self.compose_cpu_seconds - self.compose_db_seconds,
            ))
        for name, count in self.dependency_calls.items():
            values[f"{PREFIX}compose_{name}_calls"] = str(count)
            values[f"{PREFIX}compose_{name}_ms"] = ms(self.dependency_seconds[name])
        return values


__all__ = ["HandlerTiming", "dependency_span", "time_dependency"]
