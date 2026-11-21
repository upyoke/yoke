"""Recorded walk-end receipts belong to the mission runs, not cancellation time."""

from yoke_contracts.qa_case_starting_state import needs_test_machine

from typing import Any

from yoke_core.domain.db_helpers import query_one
from yoke_core.domain.qa_plan_execution_store import result_rows


def pending_mission_walks(conn: Any, execution: dict, *, captured_only: bool = False) -> list[int]:
    """Ordinals whose own walk-end restore has not been recorded."""
    results = {row["ordinal"]: row for row in result_rows(conn, str(execution["id"]))}
    pending = []
    for ordinal, case in enumerate(execution.get("roster") or []):
        if case.get("runner_id") != "agent_mission" or not needs_test_machine(case):
            continue
        row = results.get(ordinal)
        if row is None or row["requirement_id"] != case["requirement_id"]:
            if not captured_only:
                pending.append(ordinal)
            continue
        if query_one(
            conn,
            "SELECT a.id FROM qa_artifacts a JOIN qa_runs r ON r.id=a.qa_run_id "
            "WHERE a.qa_run_id=%s AND r.qa_requirement_id=%s "
            "AND a.artifact_type='starting_state_restore' LIMIT 1",
            (row["result"].get("run_id"), case["requirement_id"]),
        ) is None:
            pending.append(ordinal)
    return pending


def mission_restores_recorded(conn: Any, execution: dict) -> bool:
    """Every mission in this execution has its own recorded walk-end restore."""
    return any(
        case.get("runner_id") == "agent_mission" and needs_test_machine(case)
        for case in execution.get("roster") or []
    ) and not pending_mission_walks(conn, execution)


def release_restored_case_host(
    conn: Any, execution: dict, ordinal: int, lease_id: int
) -> bool:
    """Release this case's host unless another captured walk still needs it."""
    from yoke_core.domain.coordination_claims import release
    from yoke_core.domain.qa_case_host_custody import case_host_lease_id
    from yoke_core.domain.qa_host_turns import lock_host_turn
    from yoke_core.domain.qa_plan_execution_store import marker
    from yoke_core.domain.qa_plan_host_leases import execution_host_leases

    for claim in execution_host_leases(conn, execution):
        lock_host_turn(conn, claim.target)
    pending_leases = {
        case_host_lease_id(conn, execution, execution["roster"][index])
        for index in pending_mission_walks(conn, execution, captured_only=True)
        if index != ordinal
    } - {None}
    if lease_id not in pending_leases:
        release(conn, lease_id, "mission-teardown-finished", commit=False)
    if execution.get("test_machine_lease_id") == lease_id and lease_id not in pending_leases:
        remaining = min(pending_leases, default=None)
        p = marker(conn)
        conn.execute(
            f"UPDATE qa_plan_executions SET test_machine_lease_id={p} WHERE id={p}",
            (remaining, execution["id"]),
        )
        execution["test_machine_lease_id"] = remaining
    return bool(pending_leases)


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
    on this connection and settles itself (walk-end). It is neither locked
    again, which would wait on the caller's own lock, nor moved here.
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
        if str(row[0]) == held_id:
            continue
        execution = lock_plan_execution(conn, str(row[0]))
        if execution["state"] == "walking" and mission_restores_recorded(
            conn, execution
        ):
            finish_plan_execution(
                conn, execution, state="awaiting_walk_review",
                reason="mission-walk-handed-back", commit=False,
            )
