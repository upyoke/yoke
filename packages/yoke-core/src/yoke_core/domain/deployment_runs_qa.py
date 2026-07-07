"""QA-check helpers for deployment runs.

Owns: ``cmd_qa_add``, ``cmd_qa_list``, ``cmd_qa_update`` against the
``deployment_run_qa`` table. Status validation uses ``VALID_QA_STATUSES``
from ``deployment_runs_schema``.
"""

from __future__ import annotations

from typing import Optional

from yoke_core.domain.db_helpers import connect, iso8601_now, query_rows
from yoke_core.domain.deployment_runs_schema import VALID_QA_STATUSES, _pipe_rows


def cmd_qa_add(
    run_id: str,
    check_name: str,
    source: str,
    blocking: int,
    db_path: Optional[str] = None,
) -> str:
    """Add QA requirement to run. Returns confirmation message."""
    conn = connect(db_path)
    try:
        conn.execute(
            "INSERT INTO deployment_run_qa (run_id, check_name, source, blocking) VALUES (%s, %s, %s, %s)",
            (run_id, check_name, source, blocking),
        )
        conn.commit()
        return f"Added QA check '{check_name}' to run {run_id}"
    finally:
        conn.close()


def cmd_qa_list(run_id: str, db_path: Optional[str] = None) -> str:
    """List QA requirements for a run (pipe-delimited)."""
    conn = connect(db_path)
    try:
        rows = query_rows(
            conn,
            "SELECT id, run_id, check_name, source, blocking, status, COALESCE(updated_at,'') "
            "FROM deployment_run_qa WHERE run_id=%s ORDER BY id ASC",
            (run_id,),
        )
        return _pipe_rows(rows)
    finally:
        conn.close()


def cmd_qa_update(
    run_id: str,
    check_name: str,
    status: str,
    db_path: Optional[str] = None,
) -> Optional[str]:
    """Update QA check status. Returns error message on failure, None on success."""
    if status not in VALID_QA_STATUSES:
        return f"Error: invalid QA status '{status}'. Must be: pending, passed, failed, waived"
    conn = connect(db_path)
    try:
        conn.execute(
            "UPDATE deployment_run_qa SET status=%s, updated_at=%s WHERE run_id=%s AND check_name=%s",
            (status, iso8601_now(), run_id, check_name),
        )
        conn.commit()
        return None
    finally:
        conn.close()
