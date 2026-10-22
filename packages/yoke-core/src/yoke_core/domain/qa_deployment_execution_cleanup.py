"""Deployment run state used when settling an execution's host custody."""

from yoke_core.domain.db_helpers import query_one
from yoke_core.domain.runs import TERMINAL_RUN_STATUSES


def terminal_run_status(conn, execution):
    run_id = execution.get("deployment_run_id")
    if not run_id:
        return None
    row = query_one(conn, "SELECT status FROM deployment_runs WHERE id=%s", (run_id,))
    status = row["status"] if row else None
    if status == "failed":
        from yoke_core.domain.deployment_qa_takeover_identity import inherited_target
        from yoke_core.domain.qa_deployment_run_settlement import preserves_inherited_qa
        from yoke_core.domain.qa_plan_execution_target_snapshot import (
            decode_execution_target,
        )

        target = execution.get("execution_target") or decode_execution_target(execution)
        if (
            target
            and preserves_inherited_qa(conn, str(run_id))
            and inherited_target(conn, str(run_id), target)
        ):
            return None
    return status if status in TERMINAL_RUN_STATUSES else None


def abort_reason(conn, execution, reason):
    status = terminal_run_status(conn, execution)
    return f"{reason}; deployment run status={status}" if status else reason
