"""Bounded component diagnostics for one Shipping overview, using start timings."""

from collections import Counter
from contextvars import ContextVar
from functools import wraps
import sys
from time import monotonic

from yoke_core.api.observability import trace_context
from yoke_core.domain.deployment_start_timing import (
    emit_records,
    start_step,
    timing_scope,
)

_COMPONENTS = ContextVar("deployment_overview_components", default=None)


def overview_call(component, function, *args, **kwargs):
    state = _COMPONENTS.get()
    if state is None:
        return function(*args, **kwargs)
    started = monotonic()
    try:
        return function(*args, **kwargs)
    finally:
        state["milliseconds"][component] += (monotonic() - started) * 1000
        state["calls"][component] += 1


def overview_phase(component):
    def decorate(function):
        @wraps(function)
        def run(*args, **kwargs):
            return overview_call(component, function, *args, **kwargs)

        return run

    return decorate


def timed_overview(function):
    @wraps(function)
    def run(request):
        if (request.payload or {}).get("relevance") != "overview":
            return function(request)
        state = {"milliseconds": Counter(), "calls": Counter()}
        token = _COMPONENTS.set(state)
        try:
            with timing_scope("", collect=True) as records:
                with start_step("shipping_overview") as facts:
                    facts.update(**trace_context())
                    if request.request_id is not None:
                        facts["request_id"] = str(request.request_id)
                    try:
                        outcome = function(request)
                        rows = outcome.result_payload.get("rows") or []
                        facts.update(
                            run_count=len(rows),
                            member_count=sum(
                                len(row.get("member_items") or []) for row in rows
                            ),
                        )
                        return outcome
                    finally:
                        facts.update(
                            component_ms={
                                key: round(value, 3)
                                for key, value in state["milliseconds"].items()
                            },
                            component_calls=dict(state["calls"]),
                        )
        finally:
            _COMPONENTS.reset(token)
            # Diagnostics must not turn an otherwise valid read into a failure.
            try:
                emit_records(records, stream=sys.stderr)
            except (OSError, ValueError):
                pass

    return run


class _TimedCursor:
    def __init__(self, cursor):
        self._cursor = cursor

    def __getattr__(self, name):
        return getattr(self._cursor, name)

    def fetchall(self):
        return overview_call("db_fetch", self._cursor.fetchall)

    def fetchone(self):
        return overview_call("db_fetch", self._cursor.fetchone)

    def fetchmany(self, *args, **kwargs):
        return overview_call("db_fetch", self._cursor.fetchmany, *args, **kwargs)

    def __iter__(self):
        while (row := self.fetchone()) is not None:
            yield row


class _TimedConnection:
    def __init__(self, conn):
        self._inner = conn

    def __getattr__(self, name):
        return getattr(self._inner, name)

    def execute(self, *args, **kwargs):
        return _TimedCursor(
            overview_call("db_execute", self._inner.execute, *args, **kwargs)
        )


def overview_connection(conn):
    return _TimedConnection(conn) if _COMPONENTS.get() is not None else conn
