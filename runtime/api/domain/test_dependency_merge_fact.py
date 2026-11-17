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
from yoke_core.domain.session_control_health_facts import gating_blockers
from yoke_core.domain.workflow_runtime import builtin_workflow_runtime

CREATED = "2026-01-02T00:00:00Z"


@pytest.mark.parametrize(
    "landing,code",
    [
        ("2026-01-01T00:00:00Z", "merge_landing_predates_dependency"),
        (CREATED, "merge_landing_predates_dependency"),
        ("2026-01-02T00:00:00.000001Z", None),
        ("2026-01-01T20:00:00-05:00", None),
        (datetime(2026, 1, 3, tzinfo=timezone.utc), None),
        (None, "merge_not_landed"),
        ("", "merge_not_landed"),
        ("invalid", "merge_landing_unverified"),
    ],
)
def test_merge_fact_requires_a_strictly_later_landing(landing, code):
    verdict = evaluate_satisfaction(
        "fact:merged",
        "implementing",
        blocking_worktree="already-on-trunk",
        blocking_merged=True,
        blocking_merged_at=landing,
        dependency_created_at=CREATED,
        workflow=builtin_workflow_runtime("dash"),
    )
    assert verdict.satisfied is (code is None)
    if code is not None:
        assert verdict.reason.startswith(f"{code}:")


def test_missing_edge_clock_cannot_infer_a_landing():
    verdict = evaluate_satisfaction(
        "fact:merged",
        "release",
        blocking_merged=True,
        blocking_merged_at="2026-01-03T00:00:00Z",
        workflow=builtin_workflow_runtime("dash"),
    )
    assert not verdict.satisfied
    assert verdict.reason.startswith("merge_landing_unverified:")


@pytest.mark.parametrize("blocker_status", ["release", "done"])
def test_prior_landing_waits_until_relanding_or_done_in_all_readers(
    test_db, blocker_status
):
    blocker, dependent = 9811, 9812
    for item in (blocker, dependent):
        insert_item(
            test_db,
            id=item,
            project_sequence=item,
            workflow_id="dash",
            status=blocker_status if item == blocker else "release",
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
        ("2026-01-01T00:00:00Z", blocker_status != "done"),
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
        assert bool(gating_blockers(test_db, [dependent])) is blocked
        assert (
            _blocker_verdict(test_db, blocker, "fact:merged", CREATED).satisfied
            is not blocked
        )


@pytest.mark.parametrize(
    "landing", ["2026-01-01T00:00:00Z", "2026-01-03T00:00:00Z", CREATED, None]
)
def test_done_satisfies_merge_edge_regardless_of_landing_or_edge_age(landing):
    verdict = evaluate_satisfaction(
        "fact:merged",
        "done",
        blocking_merged_at=landing,
        dependency_created_at=CREATED,
        workflow=builtin_workflow_runtime("dash"),
    )
    assert verdict.satisfied
    assert "done" in verdict.reason


def test_completion_satisfies_merge_edge_without_clock_evidence():
    assert evaluate_satisfaction(
        "fact:merged", "done", workflow=builtin_workflow_runtime("dash")
    ).satisfied
    assert not evaluate_satisfaction("fact:merged", "done").satisfied


def _transition(conn, item_id, status, at):
    conn.execute(
        "INSERT INTO item_status_transitions "
        "(item_id,task_num,from_status,to_status,source,created_at) "
        "VALUES (%s,NULL,'idea',%s,'test',%s)",
        (item_id, status, at),
    )
    conn.execute("UPDATE items SET status=%s WHERE id=%s", (status, item_id))


def test_returned_blocker_owes_a_relanding_in_every_reader(test_db):
    blocker, dependent = 9821, 9822
    for item in (blocker, dependent):
        insert_item(
            test_db,
            id=item,
            project_sequence=item,
            workflow_id="dash",
            status="implementing",
        )
    test_db.execute(
        "INSERT INTO item_dependencies "
        "(dependent_item_id,blocking_item_id,gate_point,satisfaction,source,created_at) "
        "VALUES (%s,%s,'integration','fact:merged','test',%s)",
        (dependent, blocker, CREATED),
    )
    from yoke_core.domain.project_identity import render_item_ref

    dependent_ref = render_item_ref(test_db, dependent)

    def blocked() -> bool:
        readers = {
            "pairs": bool(unsatisfied_dependency_pairs(test_db, [dependent])),
            "batch": bool(
                dependency_planning.evaluate_batch_gates(
                    test_db, "integration", emit_events=False
                )
            ),
            "item": dependency_planning.evaluate_item_gate(
                test_db, dependent_ref, "integration"
            ).is_blocked,
            "hard": bool(evaluate_blockers(dependent, conn=test_db)),
            "gate": bool(
                dependencies.query_unsatisfied_at_gate(
                    test_db, dependent_ref, "integration"
                )
            ),
            "frontier": bool(dependencies.query_frontier_blocks(test_db, "integration")),
            "health": bool(gating_blockers(test_db, [dependent])),
            "notice": not _blocker_verdict(
                test_db, blocker, "fact:merged", CREATED
            ).satisfied,
        }
        assert len(set(readers.values())) == 1, readers
        return next(iter(readers.values()))

    land = "UPDATE items SET merged_at=%s WHERE id=%s"
    test_db.execute(land, ("2026-01-03T00:00:00Z", blocker))
    _transition(test_db, blocker, "release", "2026-01-03T00:01:00Z")
    assert not blocked()
    _transition(test_db, blocker, "implementing", "2026-01-03T00:02:00Z")
    assert blocked()
    [(_, _, verdict)] = unsatisfied_dependency_pairs(test_db, [dependent])
    assert verdict.reason.startswith("merge_relanding_owed:")
    test_db.execute(land, ("2026-01-03T01:00:00Z", blocker))
    assert not blocked()
    _transition(test_db, blocker, "release", "2026-01-03T01:01:00Z")
    assert not blocked()


def test_relanding_owed_only_before_release():
    workflow = builtin_workflow_runtime("dash")
    landed = dict(
        blocking_merged_at="2026-01-03T00:00:00Z",
        dependency_created_at=CREATED,
        workflow=workflow,
        blocking_returned_after_landing=True,
    )
    owed = evaluate_satisfaction("fact:merged", "implementing", **landed)
    assert owed.reason.startswith("merge_relanding_owed:")
    assert evaluate_satisfaction("fact:merged", "release", **landed).satisfied
    assert evaluate_satisfaction("fact:merged", "done", **landed).satisfied
