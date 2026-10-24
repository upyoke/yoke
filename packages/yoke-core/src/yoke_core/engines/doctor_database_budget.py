"""Bound Doctor SQL at statement boundaries without interrupting driver frames."""

from __future__ import annotations

from contextlib import contextmanager

from yoke_contracts.doctor_budget import (
    CHECK_BUDGET_S,
    DoctorBudgetExhausted,
    remaining_seconds,
)
from yoke_contracts.refusal_recovery import compose_refusal

from yoke_core.domain import db_backend
from yoke_core.domain.bounded_database import BudgetConnection


def driver_call(method, *args, **kwargs):
    try:
        return method(*args, **kwargs)
    except Exception as exc:
        if getattr(exc, "sqlstate", None) == "57014":
            raise DoctorBudgetExhausted("doctor_check_budget_exhausted") from exc
        raise


@contextmanager
def bounded_connection(conn):
    # Non-database checks and minimal doubles need no SQL adapter.
    if not all(callable(getattr(conn, name, None)) for name in ("execute", "cursor")):
        yield conn
        return
    is_postgres = db_backend.connection_is_postgres(conn)
    if is_postgres and not hasattr(conn, "autocommit"):
        raise RuntimeError(
            compose_refusal(
                "doctor_postgres_autocommit_unavailable: cannot bound this connection.",
                recovery=(
                    "provide a PostgreSQL connection exposing autocommit so Doctor can set and "
                    "restore its statement timeout."
                ),
            )
        )
    restore = is_postgres and conn.autocommit
    prior = None
    if restore:
        cursor = driver_call(conn.execute, "SHOW statement_timeout")
        prior = driver_call(cursor.fetchone)[0]
    try:
        yield BudgetConnection(
            conn,
            remaining=lambda: remaining_seconds(CHECK_BUDGET_S),
            driver_call=driver_call,
        )
    finally:
        if restore:
            driver_call(
                conn.execute,
                "SELECT set_config('statement_timeout', %s, false)",
                (prior,),
            )
