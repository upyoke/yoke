"""Recorded walk-end receipts belong to the mission runs, not cancellation time."""

from typing import Any

from yoke_core.domain.db_helpers import query_one
from yoke_core.domain.qa_plan_execution_store import result_rows


def mission_restores_recorded(conn: Any, execution: dict) -> bool:
    """Every mission in this execution has its own recorded walk-end restore."""
    missions = {
        ordinal: case
        for ordinal, case in enumerate(execution.get("roster") or [])
        if case.get("runner_id") == "agent_mission"
    }
    results = {row["ordinal"]: row for row in result_rows(conn, str(execution["id"]))}
    for ordinal, case in missions.items():
        row = results.get(ordinal)
        if row is None or row["requirement_id"] != case["requirement_id"]:
            return False
        if query_one(
            conn,
            "SELECT a.id FROM qa_artifacts a JOIN qa_runs r ON r.id=a.qa_run_id "
            "WHERE a.qa_run_id=%s AND r.qa_requirement_id=%s "
            "AND a.artifact_type='starting_state_restore' LIMIT 1",
            (row["result"].get("run_id"), case["requirement_id"]),
        ) is None:
            return False
    return bool(missions)
