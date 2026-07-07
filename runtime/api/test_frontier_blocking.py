"""Frontier behavior under the items.blocked flag and AC-12.

Covers:

- An item with ``blocked=1`` and a non-empty ``blocked_reason`` lands in
  ``FrontierResult.blocked`` with a reason that names the operator-supplied
  text verbatim — the AC-12 invariant against synthesizing
  ``blocking_item="unknown"`` when a real reason exists.
- A blocked-flag item lands in WAIT regardless of its preserved lifecycle
  status — implementing/refined-idea/idea all route to blocked.
- Legacy ``status='blocked'`` still classifies as blocked (drift safety)
  and surfaces the legacy reason wording; the doctor health check
  ``HC-blocked-status-drift`` is the post-cutover follow-up.
- A row with both ``blocked=1`` and an unsatisfied ``item_dependencies``
  edge surfaces both the operator reason and the typed blocker_details.
"""

from __future__ import annotations

import pytest

from yoke_core.domain import db_backend
from yoke_core.domain.frontier_compute import compute_frontier
from yoke_core.domain.scheduler import compute_schedule
from runtime.api.frontier_test_helpers import (
    insert_dep,
    insert_item,
    make_test_db,
)


def _set_blocked(conn, item_id: int, reason: str | None = None) -> None:
    p = "%s" if db_backend.connection_is_postgres(conn) else "?"
    conn.execute(
        f"UPDATE items SET blocked = 1, blocked_reason = {p} WHERE id = {p}",
        (reason, item_id),
    )


def test_blocked_flag_lands_in_blocked_partition():
    conn = make_test_db()
    insert_item(conn, 10, status="implementing")
    _set_blocked(conn, 10, "Operator decided to pause for upstream review")
    conn.commit()

    result = compute_frontier(conn, project_scope=["yoke"])
    assert len(result.blocked) == 1
    assert result.blocked[0].item_id == "YOK-10"
    assert result.runnable == []


def test_blocked_flag_reason_named_verbatim_ac12():
    conn = make_test_db()
    insert_item(conn, 10, status="refined-idea")
    _set_blocked(conn, 10, "Awaiting external API contract sign-off")
    conn.commit()

    result = compute_frontier(conn, project_scope=["yoke"])
    fi = result.blocked[0]
    # The rendered reason must surface the operator-supplied text
    # rather than a generic "unknown" placeholder.
    assert any(
        "Awaiting external API contract sign-off" in r for r in fi.blocked_reasons
    )
    assert all("unknown" not in r for r in fi.blocked_reasons)


def test_blocked_flag_with_no_reason_still_categorizes_as_blocked():
    conn = make_test_db()
    insert_item(conn, 10, status="idea")
    _set_blocked(conn, 10, None)
    conn.commit()

    result = compute_frontier(conn, project_scope=["yoke"])
    assert len(result.blocked) == 1
    assert any("operator" in r.lower() for r in result.blocked[0].blocked_reasons)


def test_blocked_flag_overrides_lifecycle_status():
    """Blocked routing fires for any preserved lifecycle status."""
    conn = make_test_db()
    insert_item(conn, 10, status="implementing")
    insert_item(conn, 11, status="refined-idea")
    insert_item(conn, 12, status="planning", item_type="epic")
    for i in (10, 11, 12):
        _set_blocked(conn, i, "test reason")
    conn.commit()

    result = compute_frontier(conn, project_scope=["yoke"])
    blocked_ids = {fi.item_id for fi in result.blocked}
    assert blocked_ids == {"YOK-10", "YOK-11", "YOK-12"}


def test_legacy_blocked_status_still_blocked_drift_safety():
    conn = make_test_db()
    insert_item(conn, 10, status="blocked")
    conn.commit()

    result = compute_frontier(conn, project_scope=["yoke"])
    assert len(result.blocked) == 1
    fi = result.blocked[0]
    assert any("legacy blocked status" in r for r in fi.blocked_reasons)


def test_blocked_flag_combines_with_dependency_blocker_details():
    """An item with both an operator block and a dependency edge surfaces both."""
    conn = make_test_db()
    insert_item(conn, 10, status="planned", item_type="epic")
    insert_item(conn, 20, status="implementing")
    insert_dep(conn, "YOK-10", "YOK-20")  # YOK-10 blocked-by YOK-20 at activation
    _set_blocked(conn, 10, "operator reason")
    conn.commit()

    result = compute_frontier(conn, project_scope=["yoke"])
    fi = next(b for b in result.blocked if b.item_id == "YOK-10")
    reasons = " | ".join(fi.blocked_reasons)
    assert "operator reason" in reasons
    # Dependency-backed blocker details are populated AC-12-compliant.
    assert fi.blocker_details, "blocker_details should be populated when deps exist"
    assert fi.blocked_by, "blocked_by should be populated when deps exist"
    assert "YOK-20" in fi.blocked_by


def test_idea_incomplete_emits_no_synthesized_gate_evaluation():
    """An idea_incomplete (title-only) item produces no GateEvaluation.

    Self-readiness conditions are not dependency edges — they have no
    blocking_item, no gate_point, and no satisfaction. blocked_reasons
    still carries the human-readable explanation.
    """
    conn = make_test_db()
    insert_item(conn, 10, status="idea", spec="")
    conn.commit()

    sched = compute_schedule(conn, project_scope=["yoke"])
    blocked = next(s for s in sched.blocked_steps if s.item_id == "YOK-10")
    assert blocked.gate_evaluations == []
    assert any(
        "idea-incomplete: idea body is title-only" in r
        for r in blocked.blocked_reasons
    )


def test_runnable_when_unblocked():
    conn = make_test_db()
    insert_item(conn, 10, status="refined-idea")
    conn.commit()

    result = compute_frontier(conn, project_scope=["yoke"])
    assert len(result.runnable) == 1
    assert result.blocked == []
