"""scheduler / session-offer never surface blocked-flag items.

The compute_schedule pipeline reads from compute_frontier; compute_frontier
partitions items.blocked=1 into FrontierResult.blocked. A blocked-flag item
is therefore never in the runnable set and never produces a CONDUCT-eligible
ScheduledStep.

These tests exercise the scheduler against a synthetic DB to verify the
contract end-to-end:
- A blocked item with status='implementing' lands in scheduler.blocked_steps,
  not conduct_eligible.
- A blocked-flag item produces no synthesized GateEvaluation rows — the
  operator reason lives in blocked_reasons, not in a fabricated gate.
- Unblocking returns the item to conduct_eligible without further action.
"""

from __future__ import annotations

from typing import Any

from yoke_core.domain.scheduler import compute_schedule, NextStep
from runtime.api.frontier_test_helpers import insert_item, make_test_db


def _block(conn: Any, item_id: int, reason: str) -> None:
    conn.execute(
        "UPDATE items SET blocked = 1, blocked_reason = %s WHERE id = %s",
        (reason, item_id),
    )


def test_blocked_implementing_item_excluded_from_conduct():
    conn = make_test_db()
    insert_item(conn, 10, status="implementing")
    _block(conn, 10, "operator paused mid-flight")
    conn.commit()

    sched = compute_schedule(conn, project_scope=["yoke"])
    eligible_ids = {s.item_id for s in sched.conduct_eligible}
    assert "YOK-10" not in eligible_ids
    blocked_ids = {s.item_id for s in sched.blocked_steps}
    assert "YOK-10" in blocked_ids


def test_blocked_step_emits_no_synthesized_gate_evaluation():
    """Operator-flagged block: no gate_evaluations, reason in blocked_reasons.

    Operator pauses are not dependency edges — there is no blocking_item,
    no gate_point, no satisfaction. The reason flows through blocked_reasons.
    """
    conn = make_test_db()
    insert_item(conn, 11, status="implementing")
    _block(conn, 11, "external sign-off pending")
    conn.commit()

    sched = compute_schedule(conn, project_scope=["yoke"])
    blocked = next(s for s in sched.blocked_steps if s.item_id == "YOK-11")
    assert blocked.gate_evaluations == []
    assert any(
        "external sign-off pending" in r for r in blocked.blocked_reasons
    )


def test_unblocking_restores_to_conduct_eligible():
    conn = make_test_db()
    insert_item(conn, 12, status="refined-idea")
    _block(conn, 12, "paused")
    conn.commit()
    sched_pre = compute_schedule(conn, project_scope=["yoke"])
    assert "YOK-12" not in {s.item_id for s in sched_pre.conduct_eligible}
    assert "YOK-12" in {s.item_id for s in sched_pre.blocked_steps}

    conn.execute("UPDATE items SET blocked = 0, blocked_reason = NULL WHERE id = 12")
    conn.commit()
    sched_post = compute_schedule(conn, project_scope=["yoke"])
    # Refined-idea is conduct-eligible (issue family) once unblocked.
    eligible = {s.item_id for s in sched_post.conduct_eligible}
    assert "YOK-12" in eligible
    blocked = {s.item_id for s in sched_post.blocked_steps}
    assert "YOK-12" not in blocked


def test_blocked_step_next_step_is_wait():
    conn = make_test_db()
    insert_item(conn, 13, status="planned", item_type="epic")
    _block(conn, 13, "epic-level pause")
    conn.commit()
    sched = compute_schedule(conn, project_scope=["yoke"])
    step = next(s for s in sched.blocked_steps if s.item_id == "YOK-13")
    assert step.next_step == NextStep.WAIT
