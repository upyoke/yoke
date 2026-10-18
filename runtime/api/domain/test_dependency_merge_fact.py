"""Dated landing facts agree across every dependency gate consumer."""

from datetime import datetime, timezone

import pytest

from runtime.api.fixtures.backlog_inserts import insert_item
from yoke_core.domain import dependencies, dependency_planning
from yoke_core.domain.check_hard_blocks import evaluate_blockers
from yoke_core.domain.dependency_satisfaction import (
    evaluate_satisfaction,
    unsatisfied_dependency_pairs,
)
from yoke_core.domain.dependency_satisfied_notice import _blocker_verdict
from yoke_core.domain.session_control_health_facts import _gating_blockers
from yoke_core.domain.workflow_runtime import builtin_workflow_runtime

CREATED = "2026-01-02T00:00:00Z"


@pytest.mark.parametrize(
    "landing,expected",
    [
        ("2026-01-01T00:00:00Z", False),
        (CREATED, False),
        ("2026-01-02T00:00:00.000001Z", True),
        ("2026-01-01T20:00:00-05:00", True),
        (datetime(2026, 1, 3, tzinfo=timezone.utc), True),
        (None, False),
        ("invalid", False),
    ],
)
def test_merge_fact_requires_a_strictly_later_landing(landing, expected):
    verdict = evaluate_satisfaction(
        "fact:merged",
        "done",
        blocking_worktree="already-on-trunk",
        blocking_merged=True,
        blocking_merged_at=landing,
        dependency_created_at=CREATED,
        workflow=builtin_workflow_runtime("dash"),
    )
    assert verdict.satisfied is expected
    if not expected:
        assert "merge_landing_" in verdict.reason


def test_missing_edge_clock_cannot_infer_a_landing():
    verdict = evaluate_satisfaction(
        "fact:merged",
        "release",
        blocking_merged=True,
        blocking_merged_at="2026-01-03T00:00:00Z",
        workflow=builtin_workflow_runtime("dash"),
    )
    assert not verdict.satisfied
    assert "merge_landing_unverified" in verdict.reason


def test_prior_landing_waits_until_relanding_in_all_readers(test_db):
    blocker, dependent = 9811, 9812
    for item in (blocker, dependent):
        insert_item(
            test_db,
            id=item,
            project_sequence=item,
            workflow_id="dash",
            status="release",
        )
    test_db.execute(
        "UPDATE items SET merged_at=%s WHERE id=%s",
        ("2026-01-01T00:00:00Z", blocker),
    )
    test_db.execute(
        "INSERT INTO item_dependencies "
        "(dependent_item_id,blocking_item_id,gate_point,satisfaction,source,created_at) "
        "VALUES (%s,%s,'integration','fact:merged','test',%s)",
        (dependent, blocker, CREATED),
    )
    from yoke_core.domain.project_identity import render_item_ref

    dependent_ref = render_item_ref(test_db, dependent)
    for landing, blocked in [
        ("2026-01-01T00:00:00Z", True),
        ("2026-01-03T00:00:00Z", False),
    ]:
        test_db.execute("UPDATE items SET merged_at=%s WHERE id=%s", (landing, blocker))
        assert bool(evaluate_blockers(dependent, conn=test_db)) is blocked
        assert (
            bool(
                dependencies.query_unsatisfied_at_gate(
                    test_db, dependent_ref, "integration"
                )
            )
            is blocked
        )
        assert (
            bool(dependencies.query_frontier_blocks(test_db, "integration")) is blocked
        )
        assert (
            dependency_planning.evaluate_item_gate(
                test_db, dependent_ref, "integration"
            ).is_blocked
            is blocked
        )
        assert (
            bool(
                dependency_planning.evaluate_batch_gates(
                    test_db, "integration", emit_events=False
                )
            )
            is blocked
        )
        assert bool(unsatisfied_dependency_pairs(test_db, [dependent])) is blocked
        assert bool(_gating_blockers(test_db, [dependent])) is blocked
        assert (
            _blocker_verdict(test_db, blocker, "fact:merged", CREATED).satisfied
            is not blocked
        )
