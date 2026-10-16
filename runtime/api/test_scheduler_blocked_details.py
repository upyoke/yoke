"""Current item flags and dependency waits retain their reasons."""

from __future__ import annotations

from yoke_core.domain.scheduler import compute_schedule
from runtime.api.frontier_test_helpers import (
    insert_dep,
    insert_item,
    make_test_db,
)


def _set_blocked(conn, item_id: int, reason: str) -> None:
    conn.execute(
        "UPDATE items SET blocked = 1, blocked_reason = %s WHERE id = %s",
        (reason, item_id),
    )


def test_dependency_block_names_real_yok_id():
    """A dependency-backed block surfaces the upstream YOK-N, not 'unknown'."""
    conn = make_test_db()
    insert_item(conn, 10, status="planned", workflow="epic")
    insert_item(conn, 20, status="implementing")
    insert_dep(conn, "YOK-10", "YOK-20")
    conn.commit()

    sched = compute_schedule(conn, project_scope=["yoke"])
    blocked = next(s for s in sched.blocked_steps if s.item_id == 10)
    blockers = {ge.blocking_item for ge in blocked.gate_evaluations}
    assert "YOK-20" in blockers
    assert "unknown" not in blockers


def test_operator_block_emits_no_synthesized_gate_evaluation():
    """An operator-set blocked flag produces no GateEvaluation.

    There is no dependency edge to describe — the operator reason lives
    in blocked_reasons, not in a synthesized gate.
    """
    conn = make_test_db()
    insert_item(conn, 10, status="implementing")
    _set_blocked(conn, 10, "Awaiting external API contract")
    conn.commit()

    sched = compute_schedule(conn, project_scope=["yoke"])
    blocked = next(s for s in sched.blocked_steps if s.item_id == 10)
    assert blocked.gate_evaluations == []
    assert any("Awaiting external API contract" in r for r in blocked.blocked_reasons)


def test_blocked_flag_with_dependency_surfaces_both():
    """Operator block + dependency edge: typed gate plus operator reason.

    The dependency edge populates gate_evaluations via the typed branch;
    the operator block contributes its message via blocked_reasons only.
    Neither path synthesizes a `"unknown"` blocker.
    """
    conn = make_test_db()
    insert_item(conn, 10, status="planned", workflow="epic")
    insert_item(conn, 20, status="implementing")
    insert_dep(conn, "YOK-10", "YOK-20")
    _set_blocked(conn, 10, "operator pause")
    conn.commit()

    sched = compute_schedule(conn, project_scope=["yoke"])
    blocked = next(s for s in sched.blocked_steps if s.item_id == 10)
    blockers = {ge.blocking_item for ge in blocked.gate_evaluations}
    assert "YOK-20" in blockers
    assert "unknown" not in blockers
    assert any("operator pause" in r for r in blocked.blocked_reasons)
