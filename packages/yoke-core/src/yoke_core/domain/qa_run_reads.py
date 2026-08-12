"""Pipe-delimited QA run reads retained for operator/debug adapters."""

from __future__ import annotations

import sys
from typing import List, Optional

from yoke_core.domain.db_helpers import connect, query_one, query_rows
from yoke_core.domain.qa_constants import _pipe_row

_RUN_SELECT = (
    "id, qa_requirement_id, performed_by, qa_kind, COALESCE(verdict,''), "
    "COALESCE(CAST(score AS TEXT),''), COALESCE(CAST(confidence AS TEXT),''), "
    "COALESCE(raw_result,''), COALESCE(CAST(duration_ms AS TEXT),''), "
    "COALESCE(started_at,''), COALESCE(completed_at,''), created_at"
)


def cmd_run_list(
    *,
    db_path: Optional[str] = None,
    requirement_id: Optional[int] = None,
) -> List[str]:
    """List runs (pipe-delimited). Returns list of formatted lines."""
    conn = connect(path=db_path)
    try:
        where = "1=1"
        params: tuple = ()
        if requirement_id is not None:
            where = "qa_requirement_id = %s"
            params = (requirement_id,)

        rows = query_rows(
            conn,
            f"SELECT {_RUN_SELECT} FROM qa_runs WHERE {where} ORDER BY id",
            params,
        )
    finally:
        conn.close()

    lines = []
    for row in rows:
        line = _pipe_row(row)
        print(line)
        lines.append(line)
    return lines


def cmd_run_get(
    run_id: int,
    *,
    db_path: Optional[str] = None,
) -> str:
    """Get a single run (pipe-delimited). Returns the formatted line."""
    if run_id is None:
        print("Usage: qa run-get <id>", file=sys.stderr)
        sys.exit(2)

    conn = connect(path=db_path)
    try:
        row = query_one(
            conn,
            f"SELECT {_RUN_SELECT} FROM qa_runs WHERE id = %s",
            (run_id,),
        )
    finally:
        conn.close()

    if row is None:
        print(f"Error: run {run_id} not found", file=sys.stderr)
        sys.exit(1)

    line = _pipe_row(row)
    print(line)
    return line


__all__ = ["cmd_run_get", "cmd_run_list"]
