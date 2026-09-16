"""What a session card may say about its held item's QA inside a release.

QA standing is a current fact with a history behind it. An earlier shape of
this reader scanned every execution a member had ever recorded and kept the
worst one, which pinned a member to a failure it had already fixed and let
one stage's failure answer for another stage's target. The reader now asks
the same acceptance projection the release-to-done gate asks, so the cases
here are the ones that distinguish a current answer from an all-history one.
"""

from __future__ import annotations

from typing import Any

from runtime.api.domain.test_deployment_qa_run_acceptance import (
    _acceptance_requirement_id,
    _settle,
)
from runtime.api.domain.test_deployment_qa_stage_execution import (
    _plan,
    _seed_run,
    _stages,
)
from yoke_core.domain.db_helpers import iso8601_now
from yoke_core.domain.deployment_qa_run_acceptance import item_release_qa


def _record_verdict(conn: Any, requirement_id: int, verdict: str) -> None:
    """One later human verdict against an already-settled acceptance."""
    now = iso8601_now()
    conn.execute(
        "INSERT INTO qa_runs("
        "qa_requirement_id,performed_by,qa_kind,verdict,verdict_reason,"
        "raw_result,started_at,completed_at,created_at"
        ") VALUES (%s,'human_review','deployment_stage_acceptance',%s,"
        "'recorded by a reviewer','{}',%s,%s,%s)",
        (requirement_id, verdict, now, now, now),
    )
    conn.commit()


def test_a_case_that_failed_and_was_rerun_to_a_pass_is_accepted(test_db) -> None:
    # The regression that motivated the rewrite: a member whose requirement
    # failed once stayed failed forever, however many times it was rerun.
    plan_id = _plan(test_db, "retry-smoke")
    _seed_run(test_db, run_id="run-retry", stages=_stages(plan_id), members=(9901,))
    _settle(test_db, run_id="run-retry", stage="item-qa", member=9901)
    requirement_id = _acceptance_requirement_id(test_db, "run-retry", "item-qa")
    _record_verdict(test_db, requirement_id, "fail")
    assert not item_release_qa(test_db, run_id="run-retry", item_id=9901).accepted

    # Same requirement, answered again. The newest verdict is the answer.
    _record_verdict(test_db, requirement_id, "pass")

    standing = item_release_qa(test_db, run_id="run-retry", item_id=9901)
    assert standing.scoped
    assert standing.accepted
    assert standing.blockers == ()


def test_a_rejected_acceptance_names_the_stage_it_blocks(test_db) -> None:
    plan_id = _plan(test_db, "rejected-smoke")
    _seed_run(test_db, run_id="run-rejected", stages=_stages(plan_id), members=(9902,))
    _settle(test_db, run_id="run-rejected", stage="item-qa", member=9902)
    requirement_id = _acceptance_requirement_id(test_db, "run-rejected", "item-qa")
    _record_verdict(test_db, requirement_id, "fail")

    standing = item_release_qa(test_db, run_id="run-rejected", item_id=9902)
    assert not standing.accepted
    # The reason a reader needs is which stage is unclear, not a bare word.
    assert "item-qa" in standing.blockers[0]
    assert "rejected" in standing.blockers[0]


def test_a_waiver_discharges_the_stage_rather_than_hiding_it(test_db) -> None:
    plan_id = _plan(test_db, "waived-smoke")
    _seed_run(test_db, run_id="run-waived", stages=_stages(plan_id), members=(9903,))
    _settle(test_db, run_id="run-waived", stage="item-qa", member=9903)
    requirement_id = _acceptance_requirement_id(test_db, "run-waived", "item-qa")
    _record_verdict(test_db, requirement_id, "fail")
    test_db.execute(
        "UPDATE qa_requirements SET waived_at=%s,waiver_rationale=%s WHERE id=%s",
        (iso8601_now(), "accepted on operator evidence", requirement_id),
    )
    test_db.commit()

    assert item_release_qa(test_db, run_id="run-waived", item_id=9903).accepted


def test_one_member_failing_leaves_its_sibling_accepted(test_db) -> None:
    # Item-scoped obligations are each member's own; a batch whose members
    # finish at different times must not report one member's gate on another.
    plan_id = _plan(test_db, "sibling-smoke")
    _seed_run(
        test_db,
        run_id="run-siblings",
        stages=_stages(plan_id),
        members=(9904, 9905),
    )
    _settle(test_db, run_id="run-siblings", stage="item-qa", member=9904)

    assert item_release_qa(test_db, run_id="run-siblings", item_id=9904).accepted
    outstanding = item_release_qa(test_db, run_id="run-siblings", item_id=9905)
    assert not outstanding.accepted
    assert "no completed scoped QA execution exists" in outstanding.blockers[0]


def test_a_legacy_release_reports_no_scoped_qa_rather_than_a_clear_one(
    test_db,
) -> None:
    # A flow with no QA stage owes nothing, which is a different answer from
    # every obligation being met — and the card must not conflate them.
    stages = [
        {
            "name": "deploy",
            "step_runner": "auto",
            "stage_kind": "execution",
            "scope": "run",
        },
        {
            "name": "promote",
            "step_runner": "auto",
            "stage_kind": "execution",
            "scope": "run",
        },
    ]
    _seed_run(test_db, run_id="run-legacy", stages=stages, members=(9906,))

    standing = item_release_qa(test_db, run_id="run-legacy", item_id=9906)
    assert standing.scoped is False
    assert standing.accepted is False
    assert standing.blockers == ()
