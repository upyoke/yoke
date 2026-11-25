"""Durable QA ownership at session lifecycle boundaries."""

from __future__ import annotations

from typing import Any

from .db_helpers import query_rows
from .qa_plan_execution_schema import LIVE_PLAN_EXECUTION_STATES
from .qa_plan_execution_store import marker
from .schema_common import _table_exists


def sessions_owning_live_qa_executions(conn: Any) -> set[str]:
    """Sessions with a live execution, irrespective of the owner's activity."""
    if not _table_exists(conn, "qa_plan_executions"):
        return set()
    states = sorted(LIVE_PLAN_EXECUTION_STATES)
    placeholders = ",".join([marker(conn)] * len(states))
    return {
        str(row["session_id"])
        for row in query_rows(
            conn,
            f"SELECT DISTINCT session_id FROM qa_plan_executions WHERE state IN ({placeholders})",
            tuple(states),
        )
    }


def session_owns_live_qa_execution(conn: Any, session_id: str) -> bool:
    """Recheck one session's live execution before changing its lifecycle."""
    if not _table_exists(conn, "qa_plan_executions"):
        return False
    states = sorted(LIVE_PLAN_EXECUTION_STATES)
    p = marker(conn)
    placeholders = ",".join([p] * len(states))
    return conn.execute(
        f"SELECT 1 FROM qa_plan_executions WHERE session_id={p} "
        f"AND state IN ({placeholders}) LIMIT 1",
        (session_id, *states),
    ).fetchone() is not None
