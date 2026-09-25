"""What a session card may say about its held item's QA inside a release.

Two earlier shapes of this reader were wrong in the same direction: both
answered a broader question than a card asks. The first scanned every
execution a member had ever recorded and kept the worst, pinning a member to
a failure it had already fixed. The second walked every QA stage the run had
pinned, so a healthy member read "not accepted" because a production check
nobody had run yet was still outstanding, and a run-scoped gate the whole
batch was waiting on read as this member's own problem.

The reader now asks the per-stage acceptance authority the release gate asks,
about one stage: the item-scoped QA stage the run has actually reached. The
cases here are the ones that separate that answer from the broader two.
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
from runtime.api.domain.test_no_obligation_member_close_out import _no_obligation
from yoke_core.domain.db_helpers import iso8601_now
from runtime.api.domain.test_deployment_qa_stage_ordering import (
    _qa_stage as _ordered_qa_stage,
)
from yoke_core.domain.deployment_qa_run_acceptance import (
    current_item_qa,
    item_qa_acceptance_blockers,
)


def _standing(conn: Any, run_id: str, item_id: int, stage: str = "item-qa"):
    """The card's reading, at the stage the run is standing on."""
    return current_item_qa(conn, run_id=run_id, item_id=item_id, current_stage=stage)


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
    assert not _standing(test_db, "run-retry", 9901).accepted

    # Same requirement, answered again. The newest verdict is the answer.
    _record_verdict(test_db, requirement_id, "pass")

    standing = _standing(test_db, "run-retry", 9901)
    assert standing.stage == "item-qa"
    assert standing.state == "accepted"
    assert standing.blockers == ()


def test_a_rejected_acceptance_names_the_stage_it_blocks(test_db) -> None:
    plan_id = _plan(test_db, "rejected-smoke")
    _seed_run(test_db, run_id="run-rejected", stages=_stages(plan_id), members=(9902,))
    _settle(test_db, run_id="run-rejected", stage="item-qa", member=9902)
    requirement_id = _acceptance_requirement_id(test_db, "run-rejected", "item-qa")
    _record_verdict(test_db, requirement_id, "fail")

    standing = _standing(test_db, "run-rejected", 9902)
    # The state is the word a card shows; the stage and the sentence are what
    # a reader opens next. All three travel rather than one standing in.
    assert standing.state == "rejected"
    assert standing.stage == "item-qa"
    assert "rejected" in standing.reason


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

    assert _standing(test_db, "run-waived", 9903).accepted


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

    assert _standing(test_db, "run-siblings", 9904).accepted
    outstanding = _standing(test_db, "run-siblings", 9905)
    assert outstanding.state == "not yet run"
    assert "no completed scoped QA execution exists" in outstanding.reason


def test_explicit_no_obligation_reads_as_discharged_on_session_card(test_db) -> None:
    plan_id = _plan(test_db, "no-obligation-standing")
    _seed_run(
        test_db,
        run_id="run-no-obligation-standing",
        stages=_stages(plan_id),
        members=(9910,),
    )
    _no_obligation(test_db, 9910, reason="nothing observable after delivery")

    standing = _standing(test_db, "run-no-obligation-standing", 9910)
    assert standing.state == "discharged"
    assert standing.blockers == ()


def test_a_release_with_no_item_qa_stage_reports_nothing(test_db) -> None:
    # A flow with no item-scoped QA stage owes this member nothing there,
    # which is a different answer from every obligation being met — and the
    # card must not conflate them.
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

    assert _standing(test_db, "run-legacy", 9906, stage="deploy") is None


def _multi_stage(plan_id: int) -> list:
    """Item QA, then a shared release gate, then a production check."""
    return [
        {
            "name": "deploy",
            "step_runner": "auto",
            "stage_kind": "execution",
            "scope": "run",
        },
        _ordered_qa_stage("item-qa", plan_id),
        _ordered_qa_stage("release-qa", plan_id, "run"),
        _ordered_qa_stage("production-qa", plan_id, "run"),
    ]


def test_a_passed_item_stage_is_accepted_while_production_qa_is_unstarted(
    test_db,
) -> None:
    # The whole point of the narrowing. A production check nobody has run is
    # the release's remaining work, not this member's, and reporting it on
    # the item pill marks every healthy item unclear until the run finishes.
    plan_id = _plan(test_db, "future-prod-smoke")
    _seed_run(
        test_db, run_id="run-future", stages=_multi_stage(plan_id), members=(9907,)
    )
    _settle(test_db, run_id="run-future", stage="item-qa", member=9907)

    standing = _standing(test_db, "run-future", 9907)
    assert standing.stage == "item-qa"
    assert standing.state == "accepted"
    # The release gate still sees the unfinished stages; only the card does not.
    assert item_qa_acceptance_blockers(test_db, run_id="run-future", item_id=9907)


def test_a_pending_run_scoped_gate_is_not_this_members_item_qa(test_db) -> None:
    # A run-scoped stage is the batch's shared wait. Two members riding one
    # release would both read "not accepted" from it, which says nothing
    # about either of them.
    plan_id = _plan(test_db, "shared-gate-smoke")
    _seed_run(
        test_db, run_id="run-shared", stages=_multi_stage(plan_id), members=(9908,)
    )
    _settle(test_db, run_id="run-shared", stage="item-qa", member=9908)
    test_db.execute(
        "UPDATE deployment_runs SET current_stage='release-qa' WHERE id=%s",
        ("run-shared",),
    )
    test_db.commit()

    standing = _standing(test_db, "run-shared", 9908, stage="release-qa")
    assert standing.stage == "item-qa"
    assert standing.state == "accepted"
