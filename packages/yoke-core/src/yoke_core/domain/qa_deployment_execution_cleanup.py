"""Deployment run state used when settling an execution's host custody."""

from yoke_core.domain.db_helpers import query_one
from yoke_core.domain.runs import TERMINAL_RUN_STATUSES


def terminal_run_status(conn, execution):
    run_id = execution.get("deployment_run_id")
    if not run_id:
        return None
    row = query_one(conn, "SELECT status FROM deployment_runs WHERE id=%s", (run_id,))
    return row["status"] if row and row["status"] in TERMINAL_RUN_STATUSES else None


def abort_reason(conn, execution, reason):
    status = terminal_run_status(conn, execution)
    return f"{reason}; deployment run status={status}" if status else reason
