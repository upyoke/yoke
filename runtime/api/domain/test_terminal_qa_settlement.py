"""Terminal item transitions must not freeze unsettled QA records."""

from __future__ import annotations

import pytest

from runtime.api.fixtures.backlog import (
    insert_event,
    insert_item,
    insert_item_worktree,
    insert_qa_requirement,
    insert_qa_run,
)
from yoke_core.domain.standalone_item_merge_receipt import RECEIPT_EVENT_NAME
from yoke_core.domain.backlog_authoritative_status_gate import (
    _run_authoritative_status_gate,
)
from yoke_core.domain.qa_review_requests import QaReviewWait


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
        "(qa_requirement_id, performed_by, qa_kind, raw_result, created_at) "
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
        insert_qa_requirement(test_db, item_id=10, blocking_mode="blocking")
    )
    test_db.execute(
        "UPDATE qa_requirements SET waived_at = %s WHERE id = %s",
        ("2026-01-01T00:00:00Z", waived_requirement),
    )
    test_db.execute(
        "INSERT INTO qa_runs "
        "(qa_requirement_id, performed_by, qa_kind, created_at) "
        "VALUES (%s, 'worktree_run', 'command', %s)",
        (waived_requirement, "2026-01-01T00:00:00Z"),
    )
    test_db.commit()

    assert _terminal_result(test_db) == {"success": True}


def _seed_merging_sha(test_db, sha: str) -> None:
    lane = insert_item_worktree(test_db, item_id=10, branch="YOK-10")
    lane_id = int(lane["id"] if hasattr(lane, "keys") else lane[0])
    test_db.execute(
        "UPDATE item_worktrees SET commit_sha = %s WHERE id = %s",
        (sha, lane_id),
    )
    test_db.commit()


def test_terminal_transition_refuses_when_nothing_materialized(test_db):
    insert_item(test_db, id=10, status="release")
    result = _terminal_result(test_db)
    assert result["error_code"] == "GATE_QA_TERMINAL_VERDICT"
    assert "no blocking QA requirement was materialized" in result["error"]
    assert "yoke qa plan run --item YOK-10" in result["error"]


def test_terminal_transition_refuses_cancelled_run(test_db):
    insert_item(test_db, id=10, status="release")
    _seed_merging_sha(test_db, "b" * 40)
    requirement_id = _row_id(insert_qa_requirement(test_db, item_id=10))
    insert_qa_run(
        test_db,
        qa_requirement_id=requirement_id,
        verdict="error",
        raw_result='{"ci_conclusion":"cancelled"}',
        completed_at="2026-01-01T00:00:01Z",
    )
    result = _terminal_result(test_db)
    assert "concluded 'error'" in result["error"]
    assert f"requirement-id {requirement_id}" in result["error"]


def test_terminal_transition_names_pending_human_review(test_db, monkeypatch):
    insert_item(test_db, id=10, status="release")
    requirement_id = _row_id(insert_qa_requirement(test_db, item_id=10))
    insert_qa_run(
        test_db,
        qa_requirement_id=requirement_id,
        performed_by="agent",
        verdict="undetermined",
        verdict_reason="The evidence conflicts.",
        completed_at="2026-01-01T00:00:01Z",
    )
    waiting = QaReviewWait(
        requirement_id,
        73,
        "The evidence conflicts.",
        ("project owner",),
    )
    monkeypatch.setattr(
        "yoke_core.domain.qa_terminal_settlement.requirement_awaits_human_review",
        lambda *_args: waiting,
    )
    result = _terminal_result(test_db)
    assert "decision request 73" in result["error"]
    assert "resolve 73 approve|reject|waive" in result["error"]


def test_terminal_transition_refuses_pass_from_an_earlier_commit(test_db):
    insert_item(test_db, id=10, status="release")
    _seed_merging_sha(test_db, "b" * 40)
    requirement_id = _row_id(insert_qa_requirement(test_db, item_id=10))
    insert_qa_run(
        test_db,
        qa_requirement_id=requirement_id,
        verdict="pass",
        raw_result='{"verification_tree":{"head_sha":"' + "a" * 40 + '"}}',
        completed_at="2026-01-01T00:00:01Z",
    )
    result = _terminal_result(test_db)
    assert "recorded SHA " + "a" * 40 in result["error"]
    assert "the merge verified " + "b" * 12 in result["error"]


def test_terminal_transition_accepts_pass_for_merging_commit(test_db):
    insert_item(test_db, id=10, status="release")
    _seed_merging_sha(test_db, "b" * 40)
    requirement_id = _row_id(insert_qa_requirement(test_db, item_id=10))
    insert_qa_run(
        test_db,
        qa_requirement_id=requirement_id,
        verdict="pass",
        raw_result='{"verification_tree":{"head_sha":"' + "b" * 40 + '"}}',
        completed_at="2026-01-01T00:00:01Z",
    )
    assert _terminal_result(test_db) == {"success": True}


def _tree_result(sha: str) -> str:
    return '{"verification_tree":{"head_sha":"' + sha + '"}}'


def _seed_merge_receipt(test_db, *, landing_sha: str, merge_sha: str) -> None:
    """Record the receipt a merge boundary writes as the branch lands."""
    insert_event(
        test_db,
        event_id=f"evt-receipt-{landing_sha[:8]}",
        event_name=RECEIPT_EVENT_NAME,
        item_id="10",
        envelope=(
            '{"context": {"branch": "YOK-10", "target": "main", '
            f'"commit_sha": "{landing_sha}", "merge_sha": "{merge_sha}"}}}}'
        ),
    )


def test_terminal_transition_accepts_the_head_the_merge_gate_verified(test_db):
    """A queue-landed item has no lane-local commit of what landed.

    The merge happens entirely on GitHub, so nothing ever records the
    integrated head on the lane; the passing merge-gate CI evidence is the
    only thing that names it, and the gate has to accept it.
    """
    insert_item(test_db, id=10, status="release")
    integrated = "c" * 40
    gate_requirement = _row_id(insert_qa_requirement(test_db, item_id=10))
    insert_qa_run(
        test_db,
        qa_requirement_id=gate_requirement,
        verdict="pass",
        performed_by="ci_run",
        raw_result=_tree_result(integrated),
        completed_at="2026-01-01T00:00:01Z",
    )

    assert _terminal_result(test_db) == {"success": True}


def test_terminal_transition_accepts_lane_and_integrated_heads_together(test_db):
    """One merge legitimately proves two trees.

    The item's own case ran against the lane head that entered the merge; the
    train's combined head is a commit that case could never have run against.
    Both are what this merge verified, so both requirements settle.
    """
    insert_item(test_db, id=10, status="release")
    lane, integrated = "d" * 40, "e" * 40
    _seed_merge_receipt(test_db, landing_sha=lane, merge_sha="f" * 40)
    item_requirement = _row_id(insert_qa_requirement(test_db, item_id=10))
    insert_qa_run(
        test_db,
        qa_requirement_id=item_requirement,
        verdict="pass",
        raw_result=_tree_result(lane),
        completed_at="2026-01-01T00:00:01Z",
    )
    gate_requirement = _row_id(insert_qa_requirement(test_db, item_id=10))
    insert_qa_run(
        test_db,
        qa_requirement_id=gate_requirement,
        verdict="pass",
        performed_by="ci_run",
        raw_result=_tree_result(integrated),
        completed_at="2026-01-01T00:00:02Z",
    )

    assert _terminal_result(test_db) == {"success": True}


def test_terminal_transition_accepts_pass_for_recorded_merge_sha(test_db):
    insert_item(test_db, id=10, status="release")
    merge_sha = "f" * 40
    _seed_merge_receipt(test_db, landing_sha="d" * 40, merge_sha=merge_sha)
    requirement_id = _row_id(insert_qa_requirement(test_db, item_id=10))
    insert_qa_run(
        test_db,
        qa_requirement_id=requirement_id,
        verdict="pass",
        raw_result=_tree_result(merge_sha),
        completed_at="2026-01-01T00:00:01Z",
    )

    assert _terminal_result(test_db) == {"success": True}


def test_flow_derived_ci_refusal_names_the_evidence_surface(test_db):
    insert_item(test_db, id=10, status="release")
    _seed_merging_sha(test_db, "b" * 40)
    requirement_id = _row_id(
        insert_qa_requirement(
            test_db,
            item_id=10,
            requirement_source="flow_derived",
            method_id="command-ci",
            method_config='{"command":"","registered_scope":"full"}',
        )
    )
    insert_qa_run(
        test_db,
        qa_requirement_id=requirement_id,
        verdict="pass",
        raw_result=_tree_result("a" * 40),
        completed_at="2026-01-01T00:00:01Z",
    )

    result = _terminal_result(test_db)

    assert "yoke qa run record-verdict --help" in result["error"]
    assert "yoke qa case run" not in result["error"]


def test_terminal_transition_still_refuses_a_head_no_merge_recorded(test_db):
    """Accepting several recorded heads must not accept an unrecorded one."""
    insert_item(test_db, id=10, status="release")
    _seed_merge_receipt(test_db, landing_sha="d" * 40, merge_sha="f" * 40)
    requirement_id = _row_id(insert_qa_requirement(test_db, item_id=10))
    insert_qa_run(
        test_db,
        qa_requirement_id=requirement_id,
        verdict="pass",
        raw_result=_tree_result("a" * 40),
        completed_at="2026-01-01T00:00:01Z",
    )

    result = _terminal_result(test_db)

    assert result["error_code"] == "GATE_QA_TERMINAL_VERDICT"
    assert "recorded SHA " + "a" * 40 in result["error"]
