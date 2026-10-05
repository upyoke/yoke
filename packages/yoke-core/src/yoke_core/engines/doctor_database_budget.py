"""Bound Doctor SQL at statement boundaries without interrupting driver frames."""

from __future__ import annotations

from contextlib import contextmanager

from yoke_contracts.doctor_budget import (
    CHECK_BUDGET_S,
    DoctorBudgetExhausted,
    remaining_seconds,
)
from yoke_core.domain import db_backend


class BudgetCursor:
    def __init__(self, cursor, conn):
        self._cursor = cursor
        self._conn = conn

    def __getattr__(self, name):
        return getattr(self._cursor, name)

    def __enter__(self):
        self._cursor.__enter__()
        return self

    def __exit__(self, *args):
        return self._cursor.__exit__(*args)

    def __iter__(self):
        return iter(self._cursor)

    def _execute(self, method, *args, **kwargs):
        try:
            self._conn._set_timeout()
            getattr(self._cursor, method)(*args, **kwargs)
        except Exception as exc:
            if getattr(exc, "sqlstate", None) == "57014":
                raise DoctorBudgetExhausted("doctor_check_budget_exhausted") from exc
            raise
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
        return getattr(self._conn, name)

    def __setattr__(self, name, value):
        setattr(self._conn, name, value)

    def _set_timeout(self):
        timeout_ms = max(1, int(remaining_seconds(CHECK_BUDGET_S) * 1000))
        if db_backend.connection_is_postgres(self._conn):
            self._conn.execute(
                "SELECT set_config('statement_timeout', %s, %s)",
                (f"{timeout_ms}ms", not self._conn.autocommit),
            )

    def cursor(self, *args, **kwargs):
        return BudgetCursor(self._conn.cursor(*args, **kwargs), self)

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
        yield conn
        return
    restore = is_postgres and conn.autocommit
    prior = conn.execute("SHOW statement_timeout").fetchone()[0] if restore else None
    try:
        yield BudgetConnection(conn)
    finally:
        if restore:
            conn.execute("SELECT set_config('statement_timeout', %s, false)", (prior,))
