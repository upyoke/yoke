"""Recognize failed group verdicts and interrupted attempts with no case result."""

from yoke_core.domain.qa_plan_execution_schema import LIVE_PLAN_EXECUTION_SQL


def group_failed(conn, group, status) -> bool:
    """An active retry owns recovery; an abandoned resultless attempt needs help."""
    if status.get("outcome") in {"blocked", "rejected"}:
        return True
    row = conn.execute(
        "SELECT e.state FROM qa_plan_executions e "
        "WHERE e.deployment_run_id=%s AND e.execution_target_digest=%s "
        "AND e.deployment_stage=%s AND e.deployment_member_item_id IS NULL "
        "ORDER BY e.execution_order DESC LIMIT 1",
        (group.run_id, group.digest, group.stage),
    ).fetchone()
    if row is None or row[0] != "aborted":
        return False
    live = conn.execute(
        "SELECT 1 FROM qa_plan_executions WHERE deployment_run_id=%s "
        "AND execution_target_digest=%s AND deployment_stage=%s "
        f"AND state IN ({LIVE_PLAN_EXECUTION_SQL}) LIMIT 1",
        (group.run_id, group.digest, group.stage),
    ).fetchone()
    recorded = conn.execute(
        "SELECT 1 FROM qa_runs WHERE qa_requirement_id=ANY(%s) LIMIT 1",
        (list(group.requirement_ids),),
    ).fetchone()
    return not live and not recorded
