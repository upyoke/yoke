"""Bounded event-row selection for retention pruning.

LIMIT caps matching rows, not scanned rows or query duration. The
monotonic pass deadline is checked only between statements; each event
preview/delete uses the existing ``set_config('statement_timeout')``
facility so a sparse scan, ORDER BY, or leftover probe cannot outlive
the remaining budget. Callers own the connection, commit, and audit row.
"""

from __future__ import annotations

import time
from typing import Any, Dict, Optional

from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import query_scalar
from yoke_core.domain.schema_common import _table_exists

EVENT_PRUNE_BATCH_SIZE = 1000
EVENT_PRUNE_BATCH_SIZE_MAX = 5000
EVENT_PRUNE_MAX_SECONDS = 30.0
SESSION_TOOL_CALLS_RETENTION_DAYS = 7
EVENT_RETENTION_DAYS: Dict[str, Optional[int]] = {
    "DEBUG": 1,
    "INFO": 30,
    "WARN": 90,
    "STATUS": None,
    "ERROR": None,
    "FATAL": None,
}
_EVENT_AUDIT_REFERENCE_TABLES = (
    "path_moves",
    "path_context_values",
    "path_integrity_repairs",
)
_STATEMENT_TIMEOUT_SQLSTATE = "57014"


class StatementBudgetExceeded(Exception):
    """One prune statement hit ``statement_timeout``; committed batches stand."""


def coerce_batch_size(raw: int) -> int:
    """Reject non-positive sizes and cap a single statement."""
    if not isinstance(raw, int) or isinstance(raw, bool) or raw < 1:
        raise ValueError("batch_size must be a positive integer")
    return min(raw, EVENT_PRUNE_BATCH_SIZE_MAX)


def remaining_timeout_ms(deadline: float) -> int:
    """Milliseconds left on the pass budget, floored at 1ms."""
    return max(1, int((deadline - time.monotonic()) * 1000))


def apply_event_prune_statement_timeout(conn: Any, deadline: float) -> None:
    """Bound the next statement to remaining pass time (Postgres only)."""
    if not db_backend.connection_is_postgres(conn):
        return
    conn.execute(
        "SELECT set_config('statement_timeout', %s, true)",
        (f"{remaining_timeout_ms(deadline)}ms",),
    )


def current_statement_timeout(conn: Any) -> str:
    """Return SHOW statement_timeout, or ``0`` off Postgres."""
    if not db_backend.connection_is_postgres(conn):
        return "0"
    row = conn.execute("SHOW statement_timeout").fetchone()
    return str(row[0] if row is not None else "0")


def restore_event_prune_statement_timeout(conn: Any, prior: str) -> None:
    """Put back the incoming timeout; never force-disable a role/session GUC."""
    if not db_backend.connection_is_postgres(conn):
        return
    conn.execute("SELECT set_config('statement_timeout', %s, true)", (prior,))


def execute_with_deadline(
    conn: Any,
    deadline: float,
    sql: str,
    params: tuple[Any, ...] = (),
    *,
    restore_timeout: str | None = None,
) -> Any:
    """Run one event SQL statement under the remaining statement_timeout.

    Event-only: a canceled statement rolls back and restores the incoming
    timeout so later helpers keep any preexisting diagnostic GUC. Callers
    restore after successful event SQL before unrelated helpers.
    """
    prior = (
        restore_timeout
        if restore_timeout is not None
        else current_statement_timeout(conn)
    )
    apply_event_prune_statement_timeout(conn, deadline)
    try:
        return conn.execute(sql, params)
    except Exception as exc:
        if not _is_statement_timeout(exc):
            raise
        conn.rollback()
        restore_event_prune_statement_timeout(conn, prior)
        raise StatementBudgetExceeded from exc


def _is_statement_timeout(exc: BaseException) -> bool:
    return (
        getattr(exc, "sqlstate", None) == _STATEMENT_TIMEOUT_SQLSTATE
        or type(exc).__name__ == "QueryCanceled"
    )


def reference_exclusion_sql(conn: Any) -> str:
    """Keep rows pinned by immutable path-audit event_id references."""
    clauses: list[str] = []
    for table in _EVENT_AUDIT_REFERENCE_TABLES:
        if _table_exists(conn, table):
            clauses.append(
                " AND event_id NOT IN "
                f"(SELECT recorded_event_id FROM {table} "
                "WHERE recorded_event_id IS NOT NULL)"
            )
    return "".join(clauses)


def format_bounded_count(count: int, partial: bool) -> str:
    """Exact N, or a labeled lower bound when the probe hit LIMIT."""
    if partial:
        return f">={count} (partial)"
    return str(count)


def bounded_event_count(
    conn: Any,
    where_sql: str,
    params: tuple[Any, ...] = (),
    *,
    limit: int,
    deadline: float | None = None,
    restore_timeout: str | None = None,
) -> tuple[int, bool]:
    """Count matching rows up to *limit*; partial means at least that many."""
    batch = coerce_batch_size(limit)
    probe = batch + 1
    sql = (
        "SELECT COUNT(*) FROM ("
        f"SELECT 1 FROM events WHERE {where_sql} LIMIT {probe}"
        ") bounded_event_count"
    )
    if deadline is None:
        found = int(query_scalar(conn, sql, params) or 0)
    else:
        row = execute_with_deadline(
            conn, deadline, sql, params, restore_timeout=restore_timeout
        ).fetchone()
        found = int((row[0] if row is not None else 0) or 0)
    if found > batch:
        return batch, True
    return found, False


def delete_event_batch(
    conn: Any,
    where_sql: str,
    params: tuple[Any, ...] = (),
    *,
    limit: int,
    deadline: float | None = None,
    restore_timeout: str | None = None,
) -> int:
    """Delete one oldest-first batch; returns rows removed this statement."""
    batch = coerce_batch_size(limit)
    # Extra subquery keeps LIMIT from being flattened out of an IN-list.
    sql = (
        "DELETE FROM events WHERE id IN ("
        "SELECT id FROM ("
        f"SELECT id FROM events WHERE {where_sql} "
        f"ORDER BY created_at, id LIMIT {batch}"
        ") bounded_event_ids)"
    )
    if deadline is None:
        cursor = conn.execute(sql, params)
    else:
        cursor = execute_with_deadline(
            conn, deadline, sql, params, restore_timeout=restore_timeout
        )
    return int(cursor.rowcount or 0)


def prune_matching_events(
    conn: Any,
    where_sql: str,
    params: tuple[Any, ...] = (),
    *,
    batch_size: int,
    deadline: float,
    batches_left: list[int | None] | None = None,
) -> tuple[int, bool]:
    """Commit LIMIT batches until drained, *deadline*, or *batches_left*.

    ``batches_left`` is a one-element remaining-batch budget shared across
    severity loops (``[None]`` means unlimited). Returns
    ``(deleted, more_remaining)``. A statement timeout is a graceful
    stop: already-committed batches stay and leftovers remain eligible.
    """
    batch = coerce_batch_size(batch_size)
    prior = current_statement_timeout(conn)
    deleted = 0
    try:
        while time.monotonic() < deadline:
            remaining = None if batches_left is None else batches_left[0]
            if remaining is not None and remaining <= 0:
                leftover, _ = bounded_event_count(
                    conn,
                    where_sql,
                    params,
                    limit=1,
                    deadline=deadline,
                    restore_timeout=prior,
                )
                return deleted, leftover > 0
            removed = delete_event_batch(
                conn,
                where_sql,
                params,
                limit=batch,
                deadline=deadline,
                restore_timeout=prior,
            )
            conn.commit()
            if removed == 0:
                return deleted, False
            deleted += removed
            if batches_left is not None and batches_left[0] is not None:
                batches_left[0] -= 1
            if removed < batch:
                return deleted, False
        leftover, _ = bounded_event_count(
            conn,
            where_sql,
            params,
            limit=1,
            deadline=deadline,
            restore_timeout=prior,
        )
        return deleted, leftover > 0
    except StatementBudgetExceeded:
        return deleted, True
    finally:
        restore_event_prune_statement_timeout(conn, prior)
