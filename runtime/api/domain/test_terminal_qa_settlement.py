"""Terminal item transitions must not freeze unsettled QA records."""

from __future__ import annotations

import pytest

from runtime.api.fixtures.backlog import (
    insert_item,
    insert_qa_requirement,
    insert_qa_run,
)
from yoke_core.domain.backlog_authoritative_status_gate import (
    _run_authoritative_status_gate,
)


def _row_id(row) -> int:
    return int(row["id"] if hasattr(row, "keys") else row[0])


def _terminal_result(test_db) -> dict:
    return _run_authoritative_status_gate(
        item_id=10,
        target_status="done",
        db_path="",
        qa_bypass=True,
        force=True,
        conn=test_db,
    ) or {"success": True}


def _seed_plan_execution(test_db, *, state: str) -> None:
    test_db.execute(
        "INSERT INTO qa_plan_executions "
        "(id, item_id, transition_id, session_id, roster_digest, roster_json, "
        "cursor_ordinal, state, created_at, heartbeat_at) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
        (
            f"execution-{state}",
            10,
            "reviewing-implementation",
            "session-1",
            "digest",
            "[]",
            0,
            state,
            "2026-01-01T00:00:00Z",
            "2026-01-01T00:00:00Z",
        ),
    )
    test_db.commit()


def test_terminal_transition_refuses_pending_run_despite_bypass_flags(test_db):
    insert_item(test_db, id=10, status="release")
    requirement_id = _row_id(
        insert_qa_requirement(test_db, item_id=10, blocking_mode="non_blocking")
    )
    test_db.execute(
        "INSERT INTO qa_runs "
        "(qa_requirement_id, executor_type, qa_kind, raw_result, created_at) "
        "VALUES (%s, 'worktree_run', 'command', %s, %s)",
        (requirement_id, '{"timed_out": true}', "2026-01-01T00:00:00Z"),
    )
    test_db.commit()

    result = _terminal_result(test_db)

    assert result["success"] is False
    assert result["error_code"] == "GATE_QA_TERMINAL_SETTLEMENT"
    assert "timed out without a verdict" in result["error"]


@pytest.mark.parametrize("state", ["active", "waiting", "awaiting_agent_review"])
def test_terminal_transition_refuses_live_plan_execution(test_db, state):
    insert_item(test_db, id=10, status="release")
    _seed_plan_execution(test_db, state=state)

    result = _terminal_result(test_db)

    assert result["success"] is False
    assert result["error_code"] == "GATE_QA_TERMINAL_SETTLEMENT"
    assert f"{state} execution remains active" in result["error"]


def test_terminal_transition_allows_settled_or_waived_records(test_db):
    insert_item(test_db, id=10, status="release")
    settled_requirement = _row_id(
        insert_qa_requirement(test_db, item_id=10, blocking_mode="non_blocking")
    )
    insert_qa_run(
        test_db,
        qa_requirement_id=settled_requirement,
        verdict="fail",
        raw_result='{"timed_out": true}',
    )
    waived_requirement = _row_id(
        insert_qa_requirement(test_db, item_id=10, blocking_mode="non_blocking")
    )
    test_db.execute(
        "UPDATE qa_requirements SET waived_at = %s WHERE id = %s",
        ("2026-01-01T00:00:00Z", waived_requirement),
    )
    test_db.execute(
        "INSERT INTO qa_runs "
        "(qa_requirement_id, executor_type, qa_kind, created_at) "
        "VALUES (%s, 'worktree_run', 'command', %s)",
        (waived_requirement, "2026-01-01T00:00:00Z"),
    )
    test_db.commit()

    assert _terminal_result(test_db) == {"success": True}
