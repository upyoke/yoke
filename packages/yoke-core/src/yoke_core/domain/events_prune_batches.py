"""Bounded event-row selection for retention pruning.

Keeps preview counts and DELETE statements inside a LIMIT so a large
``events`` table cannot force a full-table count or a single unbounded
delete. Callers own the connection, commit, deadline, and audit row.
"""

from __future__ import annotations

import time
from typing import Any, Dict, Optional

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


def coerce_batch_size(raw: int) -> int:
    """Reject non-positive sizes and cap a single statement."""
    if not isinstance(raw, int) or isinstance(raw, bool) or raw < 1:
        raise ValueError("batch_size must be a positive integer")
    return min(raw, EVENT_PRUNE_BATCH_SIZE_MAX)


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
) -> tuple[int, bool]:
    """Count matching rows up to *limit*; partial means at least that many."""
    batch = coerce_batch_size(limit)
    probe = batch + 1
    sql = (
        "SELECT COUNT(*) FROM ("
        f"SELECT 1 FROM events WHERE {where_sql} LIMIT {probe}"
        ") bounded_event_count"
    )
    found = int(query_scalar(conn, sql, params) or 0)
    if found > batch:
        return batch, True
    return found, False


def delete_event_batch(
    conn: Any,
    where_sql: str,
    params: tuple[Any, ...] = (),
    *,
    limit: int,
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
    return int(conn.execute(sql, params).rowcount or 0)


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
    ``(deleted, more_remaining)``.
    """
    batch = coerce_batch_size(batch_size)
    deleted = 0
    while time.monotonic() < deadline:
        remaining = None if batches_left is None else batches_left[0]
        if remaining is not None and remaining <= 0:
            leftover, _ = bounded_event_count(conn, where_sql, params, limit=1)
            return deleted, leftover > 0
        removed = delete_event_batch(conn, where_sql, params, limit=batch)
        conn.commit()
        if removed == 0:
            return deleted, False
        deleted += removed
        if batches_left is not None and batches_left[0] is not None:
            batches_left[0] -= 1
        if removed < batch:
            return deleted, False
    leftover, _ = bounded_event_count(conn, where_sql, params, limit=1)
    return deleted, leftover > 0
