"""Where one steering report request spends its time, as call telemetry.

The handler's served duration is the only latency Production records, and
measured from outside it hides which part dominates: the database answers a
statement in a fraction of a millisecond and a build issues a few hundred, yet
served builds take seconds. These timings split one request into its phases,
count its statements and the time spent inside them, and give the thread's own
CPU, so ``wall - cpu - db`` names the time spent waiting for neither.

Telemetry only: the values ride on the call event's handler context and no
code reads them back.
"""

from __future__ import annotations

from contextlib import contextmanager
from time import perf_counter, thread_time
from typing import Any, Dict, Iterator

PREFIX = "steering_report_"


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

    def counted(self, conn: Any) -> Any:
        return _CountedConnection(conn, self)

    @contextmanager
    def phase(self, name: str) -> Iterator[None]:
        started = perf_counter()
        try:
            yield
        finally:
            self.phases[name] = self.phases.get(name, 0.0) + perf_counter() - started

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
        return values


__all__ = ["HandlerTiming"]
