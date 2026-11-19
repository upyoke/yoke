"""Recorded walk-end receipts belong to the mission runs, not cancellation time."""

from yoke_contracts.qa_case_starting_state import needs_test_machine

from typing import Any

from yoke_core.domain.db_helpers import query_one
from yoke_core.domain.qa_plan_execution_store import result_rows


def mission_restores_recorded(conn: Any, execution: dict) -> bool:
    """Every mission in this execution has its own recorded walk-end restore."""
    missions = {
        ordinal: case
        for ordinal, case in enumerate(execution.get("roster") or [])
        if case.get("runner_id") == "agent_mission" and needs_test_machine(case)
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


def post_capture_state(conn: Any, execution: dict) -> str:
    """Mission preparation opens the walk; recorded hand-backs open review."""
    missions = any(
        case.get("runner_id") == "agent_mission" and needs_test_machine(case)
        for case in execution.get("roster") or []
    )
    return (
        "walking"
        if missions and not mission_restores_recorded(conn, execution)
        else "awaiting_walk_review"
    )


def hand_back_mission_walk(
    conn: Any,
    *,
    artifact_type: str,
    run_id: int,
    locked_execution: dict | None = None,
) -> None:
    """Move a walk whose restores are all recorded to review; never commits.

    ``locked_execution`` is an execution the caller already holds FOR UPDATE
    on this connection. It is reused as held: locking it again from another
    connection would wait on the caller's own lock and time out.
    """
    from yoke_core.domain.sql_json import json_get
    from yoke_core.domain.qa_plan_execution_store import lock_plan_execution
    from yoke_core.domain.qa_plan_execution_lifecycle import finish_plan_execution

    if artifact_type != "starting_state_restore":
        return
    rows = conn.execute(
        "SELECT DISTINCT e.id FROM qa_plan_executions e "
        "JOIN qa_plan_execution_results r ON r.execution_id=e.id "
        "WHERE e.state='walking' AND CAST("
        + json_get("r.result_json", "$.run_id")
        + " AS TEXT)=%s ORDER BY e.id",
        (str(run_id),),
    ).fetchall()
    held_id = str(locked_execution["id"]) if locked_execution else None
    for row in rows:
        execution = (
            locked_execution
            if str(row[0]) == held_id
            else lock_plan_execution(conn, str(row[0]))
        )
        if execution["state"] == "walking" and mission_restores_recorded(
            conn, execution
        ):
            finish_plan_execution(
                conn, execution, state="awaiting_walk_review",
                reason="mission-walk-handed-back", commit=False,
            )
