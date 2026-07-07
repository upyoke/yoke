"""Audit-row writers for the path-integrity repair surface.

Owns the ``path_integrity_repairs`` row lifecycle (preparing → applied
/ failed / abandoned), the matching ``path_integrity_failures``
``repair_status`` updates, and the ``unrepaired_failure_count``
bookkeeping on ``path_integrity_runs``. Public callers go through
:mod:`yoke_core.domain.path_integrity_repair`; this module is the
internal write surface.
"""

from __future__ import annotations

import json
from typing import Any, Optional

from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import iso8601_now


STATUS_PREPARING = "preparing"
STATUS_APPLIED = "applied"
STATUS_FAILED = "failed"
STATUS_ABANDONED = "abandoned"

FAILURE_OPEN = "open"
FAILURE_REPAIRED = "repaired"
FAILURE_ABANDONED = "abandoned"


def _p(conn) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _nonnegative_decrement_expr(conn) -> str:
    if db_backend.connection_is_postgres(conn):
        return "GREATEST(0, unrepaired_failure_count - 1)"
    return "MAX(0, unrepaired_failure_count - 1)"


def open_repair_row(
    conn: Any,
    *,
    failure_id: int,
    operation: str,
    arguments: dict,
) -> int:
    p = _p(conn)
    cur = conn.execute(
        "INSERT INTO path_integrity_repairs "
        "(failure_id, operation, status, requested_at, arguments) "
        f"VALUES ({p}, {p}, {p}, {p}, {p}) RETURNING id",
        (failure_id, operation, STATUS_PREPARING, iso8601_now(),
         json.dumps(arguments, sort_keys=True)),
    )
    repair_id = int(cur.fetchone()[0])
    conn.commit()
    return repair_id


def close_repair_row(
    conn: Any,
    *,
    repair_id: int,
    status: str,
    error_text: Optional[str] = None,
    recorded_event_id: Optional[str] = None,
) -> None:
    p = _p(conn)
    conn.execute(
        "UPDATE path_integrity_repairs "
        f"SET status={p}, applied_at={p}, error_text={p}, "
        f"    recorded_event_id={p} "
        f"WHERE id={p}",
        (status,
         iso8601_now() if status == STATUS_APPLIED else None,
         error_text, recorded_event_id, repair_id),
    )
    conn.commit()


def mark_failure_repaired(
    conn: Any, failure_id: int
) -> None:
    p = _p(conn)
    conn.execute(
        "UPDATE path_integrity_failures "
        f"SET repair_status={p} WHERE id={p}",
        (FAILURE_REPAIRED, failure_id),
    )
    conn.execute(
        "UPDATE path_integrity_runs "
        f"SET unrepaired_failure_count = {_nonnegative_decrement_expr(conn)} "
        "WHERE id = ("
        f"    SELECT run_id FROM path_integrity_failures WHERE id={p}"
        ")",
        (failure_id,),
    )
    conn.commit()


def write_abandon_row(
    conn: Any,
    *,
    failure_id: int,
    reason: str,
) -> int:
    arguments = {"reason": reason}
    p = _p(conn)
    cur = conn.execute(
        "INSERT INTO path_integrity_repairs "
        "(failure_id, operation, status, requested_at, applied_at, "
        " arguments, abandon_reason) "
        f"VALUES ({p}, 'abandon', {p}, {p}, {p}, {p}, {p}) RETURNING id",
        (failure_id, STATUS_ABANDONED, iso8601_now(), iso8601_now(),
         json.dumps(arguments, sort_keys=True), reason),
    )
    repair_id = int(cur.fetchone()[0])
    conn.execute(
        "UPDATE path_integrity_failures "
        f"SET repair_status={p} WHERE id={p}",
        (FAILURE_ABANDONED, failure_id),
    )
    conn.execute(
        "UPDATE path_integrity_runs "
        f"SET unrepaired_failure_count = {_nonnegative_decrement_expr(conn)} "
        "WHERE id = ("
        f"    SELECT run_id FROM path_integrity_failures WHERE id={p}"
        ")",
        (failure_id,),
    )
    conn.commit()
    return repair_id


def fetch_failure_row(
    conn: Any, failure_id: int
):
    p = _p(conn)
    return conn.execute(
        "SELECT id, run_id, invariant_kind, target_id, repair_status, "
        "       details "
        f"FROM path_integrity_failures WHERE id={p}",
        (failure_id,),
    ).fetchone()


def fetch_project_for_run(
    conn: Any, run_id: int
) -> Optional[str]:
    p = _p(conn)
    row = conn.execute(
        f"SELECT project_id FROM path_integrity_runs WHERE id={p}",
        (run_id,),
    ).fetchone()
    if row is None:
        return None
    return str(row[0])


__all__ = [
    "FAILURE_ABANDONED",
    "FAILURE_OPEN",
    "FAILURE_REPAIRED",
    "STATUS_ABANDONED",
    "STATUS_APPLIED",
    "STATUS_FAILED",
    "STATUS_PREPARING",
    "close_repair_row",
    "fetch_failure_row",
    "fetch_project_for_run",
    "mark_failure_repaired",
    "open_repair_row",
    "write_abandon_row",
]
