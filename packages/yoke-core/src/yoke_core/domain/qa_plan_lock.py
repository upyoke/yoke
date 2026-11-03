"""Bound QA definition and execution locks using the run-row savepoint pattern."""

from contextlib import contextmanager

from yoke_contracts.refusal_recovery import compose_refusal
from yoke_core.domain import db_backend
from yoke_core.domain.db_savepoint import savepoint

QA_PLAN_LOCK_TIMEOUT_MS = 2000
QA_PLAN_BUSY_CODE = "qa_plan_busy"


class QaPlanBusy(RuntimeError):
    """A QA lock did not settle; dispatch must preserve its retryable answer."""


@contextmanager
def bounded_plan_lock(conn, table: str):
    """Bound a QA lock attempt and restore the caller's timeout and transaction.

    Take the table's write mode too, so a later write cannot queue outside
    the bound. Roll back only this savepoint on refusal; never the caller's
    transaction. SQLite retains its existing locking semantics.
    """
    if not db_backend.connection_is_postgres(conn):
        yield
        return
    if table not in {"qa_plans", "qa_plan_executions"}:
        raise ValueError("unsupported QA lock table")
    import psycopg

    previous = conn.execute("SELECT current_setting('lock_timeout')").fetchone()[0]
    try:
        with savepoint(conn, "yoke_qa_plan_lock", owns=False):
            conn.execute(
                "SELECT set_config('lock_timeout', %s, true)",
                (f"{QA_PLAN_LOCK_TIMEOUT_MS}ms",),
            )
            conn.execute(f"LOCK TABLE {table} IN ROW EXCLUSIVE MODE")
            yield
            conn.execute(
                "SELECT set_config('lock_timeout', %s, true)", (str(previous),)
            )
    except (psycopg.errors.LockNotAvailable, psycopg.errors.QueryCanceled):
        raise QaPlanBusy(compose_refusal(
            f"{QA_PLAN_BUSY_CODE}: {table} stayed locked past "
            f"{QA_PLAN_LOCK_TIMEOUT_MS}ms; this lock attempt was rolled back",
            recovery="Retry the same command after the other QA writer finishes",
        )) from None
