"""Bound Doctor SQL at statement boundaries without interrupting driver frames."""

from __future__ import annotations

from contextlib import contextmanager

from yoke_contracts.doctor_budget import (
    CHECK_BUDGET_S,
    remaining_seconds,
)
from yoke_core.domain import db_backend
from yoke_core.engines.doctor_wall_clock_budget import driver_call


class BudgetCursor:
    def __init__(self, cursor, conn):
        self._cursor = cursor
        self._conn = conn

    def __getattr__(self, name):
        value = getattr(self._cursor, name)
        if callable(value):
            return lambda *a, **k: driver_call(value, *a, **k)
        return value

    def __enter__(self):
        driver_call(self._cursor.__enter__)
        return self

    def __exit__(self, *args):
        return driver_call(self._cursor.__exit__, *args)

    def __iter__(self):
        iterator = driver_call(iter, self._cursor)
        while True:
            try:
                row = driver_call(next, iterator)
            except StopIteration:
                return
            remaining_seconds(CHECK_BUDGET_S)
            yield row

    def _execute(self, method, *args, **kwargs):
        self._conn._set_timeout()
        driver_call(getattr(self._cursor, method), *args, **kwargs)
        remaining_seconds(CHECK_BUDGET_S)
        return self

    def execute(self, *args, **kwargs):
        return self._execute("execute", *args, **kwargs)

    def executemany(self, *args, **kwargs):
        return self._execute("executemany", *args, **kwargs)


class BudgetConnection:
    def __init__(self, conn):
        object.__setattr__(self, "_conn", conn)

    def __getattr__(self, name):
        value = getattr(self._conn, name)
        if callable(value):
            return lambda *a, **k: driver_call(value, *a, **k)
        return value

    def __setattr__(self, name, value):
        setattr(self._conn, name, value)

    def _set_timeout(self):
        timeout_ms = max(1, int(remaining_seconds(CHECK_BUDGET_S) * 1000))
        if db_backend.connection_is_postgres(self._conn):
            driver_call(
                self._conn.execute,
                "SELECT set_config('statement_timeout', %s, %s)",
                (f"{timeout_ms}ms", not self._conn.autocommit),
            )

    def cursor(self, *args, **kwargs):
        return BudgetCursor(driver_call(self._conn.cursor, *args, **kwargs), self)

    def execute(self, *args, **kwargs):
        return self.cursor().execute(*args, **kwargs)


@contextmanager
def bounded_connection(conn):
    # Non-database checks and minimal doubles need no SQL adapter.
    if not all(callable(getattr(conn, name, None)) for name in ("execute", "cursor")):
        yield conn
        return
    is_postgres = db_backend.connection_is_postgres(conn)
    if is_postgres and not hasattr(conn, "autocommit"):
        raise RuntimeError(
            "doctor_postgres_autocommit_unavailable: cannot bound this connection. "
            "Recovery: provide a PostgreSQL connection exposing autocommit "
            "so Doctor can set and restore its statement timeout."
        )
    restore = is_postgres and conn.autocommit
    prior = None
    if restore:
        cursor = driver_call(conn.execute, "SHOW statement_timeout")
        prior = driver_call(cursor.fetchone)[0]
    try:
        yield BudgetConnection(conn)
    finally:
        if restore:
            driver_call(
                conn.execute,
                "SELECT set_config('statement_timeout', %s, false)",
                (prior,),
            )
