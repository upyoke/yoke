"""Deployment run state used when settling an execution's host custody."""

from yoke_core.domain.db_helpers import query_one
from yoke_core.domain.runs import TERMINAL_RUN_STATUSES


def terminal_run_status(conn, execution):
    run_id = execution.get("deployment_run_id")
    if not run_id:
        return None
    row = query_one(conn, "SELECT status FROM deployment_runs WHERE id=%s", (run_id,))
    status = row["status"] if row else None
    from yoke_core.domain.deployment_run_set_aside_qa import preserved_qa_selector

    if preserved_qa_selector(conn, run_id)(execution):
        return None
    if status == "failed":
        return None  # Open executions retain custody until retry or takeover.
    return status if status in TERMINAL_RUN_STATUSES else None


def abort_reason(conn, execution, reason):
    run_id = execution.get("deployment_run_id")
    row = query_one(conn, "SELECT status FROM deployment_runs WHERE id=%s", (run_id,)) if run_id else None
    status = row["status"] if row else None
    return f"{reason}; deployment run status={status}" if status in TERMINAL_RUN_STATUSES else reason
