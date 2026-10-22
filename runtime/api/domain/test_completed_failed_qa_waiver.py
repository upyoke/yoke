"""Full scoped discharge answers failed executions without rewriting evidence."""

from __future__ import annotations

import pytest

from runtime.api.domain.test_deployment_qa_case_discharge import (
    MEMBER,
    STAGE,
    _acceptance,
    _corrected_case,
    _execute_stage,
    _seed,
    _status,
)
from runtime.api.domain.test_deployment_delivery_close_out_notice import _project
from runtime.api.domain.test_no_obligation_member_close_out import _landing_evidence
from runtime.api.domain.test_deployment_delivery_close_out_notice import _parked_owner
from runtime.api.fixtures.workflow_pins import current_workflow_pin_if_available
from runtime.api.domain.test_status_transition_preflight import _isolate_status_effects
from runtime.api.fixtures.backlog_inserts import insert_qa_requirement
from yoke_core.domain.deployment_qa_stage_acceptance import STAGE_DISCHARGED
from yoke_core.domain.qa_requirement_ops import waive_requirement
from yoke_core.domain.qa_settlement_followups import replay_settlement_followups


def _ready_member(conn, item_id, holder):
    workflow, version = current_workflow_pin_if_available(conn, "dash")
    conn.execute(
        "UPDATE items SET workflow_id=%s,workflow_version_id=%s,status='release' WHERE id=%s",
        (workflow, version, item_id),
    )
    conn.commit()
    _parked_owner(conn, holder, item_id)
    _landing_evidence(conn, item_id)


def _waive(conn, requirement):
    waive_requirement(
        conn,
        requirement,
        "operator accepts failed evidence",
        source="operator",
        force=True,
    )


def _history(conn, requirement):
    return tuple(
        tuple(row)
        for row in conn.execute(
            "SELECT id,verdict,raw_result,completed_at FROM qa_runs "
            "WHERE qa_requirement_id=%s ORDER BY id",
            (requirement,),
        ).fetchall()
    )


def test_full_waiver_after_completed_failure_preserves_history(test_db):
    run = "run-completed-failure-waived"
    requirement = _seed(test_db, run)
    _execute_stage(test_db, run, {requirement: "fail"})
    assert not _acceptance(test_db, run).accepted
    history = _history(test_db, requirement)
    _waive(test_db, requirement)
    assert _acceptance(test_db, run).state == STAGE_DISCHARGED
    status = _status(test_db, run)
    assert status["accepted"] and status["outcome"] == "discharged"
    assert _history(test_db, requirement) == history
    assert history[0][1] == "fail"


def test_partial_waiver_after_completed_failure_blocks_both_readers(test_db):
    run = "run-completed-failure-partial"
    first = _seed(test_db, run)
    second = _corrected_case(test_db, broken_id=first)
    _execute_stage(test_db, run, {first: "fail", second: "fail"})
    _waive(test_db, first)
    assert not _acceptance(test_db, run).accepted
    assert not _status(test_db, run)["accepted"]
    _waive(test_db, second)
    assert _acceptance(test_db, run).state == STAGE_DISCHARGED
    assert _status(test_db, run)["accepted"]


@pytest.mark.parametrize(
    "column,value",
    [
        ("deployment_member_item_id", MEMBER + 1),
        ("execution_target_digest", "foreign-target"),
    ],
)
def test_foreign_waiver_cannot_answer_completed_failure(test_db, column, value):
    run = "run-completed-failure-foreign"
    requirement = _seed(test_db, run)
    _execute_stage(test_db, run, {requirement: "fail"})
    foreign = _corrected_case(test_db, broken_id=requirement)
    test_db.execute(
        f"UPDATE qa_requirements SET {column}=%s WHERE id=%s", (value, foreign)
    )
    test_db.commit()
    _waive(test_db, foreign)
    assert not _acceptance(test_db, run).accepted
    assert not _status(test_db, run)["accepted"]


def test_waiver_followup_closes_failed_member_once(test_db, monkeypatch):
    from yoke_core.domain import backlog

    _isolate_status_effects(monkeypatch)
    _project(test_db)
    run = "run-failed-member-followup"
    requirement = _seed(test_db, run)
    _execute_stage(test_db, run, {requirement: "fail"})
    from runtime.api.fixtures.deployment_scoped_qa_run_fixture import (
        record_case_verdict,
    )

    record_case_verdict(test_db, requirement, "fail", evidence=True)
    _ready_member(test_db, MEMBER, "failed-member-owner")
    test_db.execute(
        "UPDATE items SET deployment_flow=%s WHERE id=%s", (f"flow-{run}", MEMBER)
    )
    test_db.execute(
        "UPDATE deployment_run_items SET delivery_intent='final' WHERE run_id=%s",
        (run,),
    )
    test_db.commit()
    history = _history(test_db, requirement)
    artifacts = tuple(
        tuple(row)
        for row in test_db.execute(
            "SELECT * FROM qa_artifacts WHERE qa_run_id IN "
            "(SELECT id FROM qa_runs WHERE qa_requirement_id=%s)",
            (requirement,),
        ).fetchall()
    )
    assert artifacts
    writes = []
    original = backlog.execute_update

    def update(*args, **kwargs):
        writes.append((args, kwargs))
        return original(*args, **kwargs)

    monkeypatch.setattr(backlog, "execute_update", update)
    _waive(test_db, requirement)
    replay_settlement_followups(test_db)
    assert (
        test_db.execute("SELECT status FROM items WHERE id=%s", (MEMBER,)).fetchone()[0]
        == "done"
    )
    count = len(writes)
    assert count == 1
    replay_settlement_followups(test_db)
    assert len(writes) == count
    assert _history(test_db, requirement) == history
    assert (
        tuple(
            tuple(row)
            for row in test_db.execute(
                "SELECT * FROM qa_artifacts WHERE qa_run_id IN "
                "(SELECT id FROM qa_runs WHERE qa_requirement_id=%s)",
                (requirement,),
            ).fetchall()
        )
        == artifacts
    )


@pytest.mark.parametrize("member", [MEMBER])
def test_unrelated_run_obligation_still_blocks_member_closeout(
    test_db, monkeypatch, member
):
    from yoke_core.domain.no_obligation_member_close_out import (
        satisfied_delivery_member,
    )

    _isolate_status_effects(monkeypatch)
    _project(test_db)
    run = "run-failed-member-other-gate"
    requirement = _seed(test_db, run)
    _execute_stage(test_db, run, {requirement: "fail"})
    _ready_member(test_db, MEMBER, "other-gate-owner")
    test_db.execute(
        "UPDATE items SET deployment_flow=%s WHERE id=%s", (f"flow-{run}", MEMBER)
    )
    test_db.commit()
    insert_qa_requirement(
        test_db,
        item_id=None,
        deployment_run_id=run,
        deployment_member_item_id=member,
        deployment_stage="other-qa",
        qa_kind="plan_case",
        qa_phase="post_deploy",
        blocking_mode="blocking",
    )
    _waive(test_db, requirement)
    replay_settlement_followups(test_db)
    assert not satisfied_delivery_member(test_db, item_id=MEMBER, run_id=run)
    assert (
        test_db.execute("SELECT status FROM items WHERE id=%s", (MEMBER,)).fetchone()[0]
        == "release"
    )


def test_run_scoped_stage_still_blocks_after_member_failure_is_waived(test_db):
    from runtime.api.domain.test_deployment_qa_stage_execution import (
        _plan,
        _seed_run,
        _stages,
    )
    from yoke_core.domain.deployment_qa_stage_materialization import (
        materialize_deployment_qa_stage,
    )
    from yoke_core.domain.deployment_qa_run_acceptance import (
        item_qa_acceptance_blockers,
    )

    run = "run-failed-member-run-gate"
    plan = _plan(test_db, "failed-member-run-gate")
    stages = _stages(plan)
    stages.append({**stages[1], "name": "release-qa", "scope": "run"})
    _seed_run(test_db, run_id=run, stages=stages, members=(MEMBER,))
    materialize_deployment_qa_stage(
        test_db,
        deployment_run_id=run,
        deployment_stage=STAGE,
        deployment_member_item_id=MEMBER,
    )
    requirement = test_db.execute(
        "SELECT id FROM qa_requirements WHERE deployment_run_id=%s AND method_id IS NOT NULL",
        (run,),
    ).fetchone()[0]
    _execute_stage(test_db, run, {requirement: "fail"})
    _waive(test_db, requirement)
    assert _acceptance(test_db, run).state == STAGE_DISCHARGED
    blockers = item_qa_acceptance_blockers(test_db, run_id=run, item_id=MEMBER)
    assert any("release-qa" in reason for reason in blockers)
    assert not any("item-qa" in reason for reason in blockers)


def test_shared_subject_still_requires_every_group_after_failed_waiver(test_db):
    from runtime.api.domain.test_deployment_qa_shared_plans import (
        MEMBERS,
        RUN,
        _seed as seed_shared,
        _materialize,
        _begin,
        _attach,
    )
    from runtime.api.domain.test_deployment_qa_stage_execution import (
        _complete_case,
        _plan,
    )
    from yoke_core.domain.deployment_qa_run_acceptance import (
        item_qa_acceptance_blockers,
    )

    seed_shared(test_db)
    requirement = _materialize(test_db, MEMBERS[0])["created_requirement_ids"][0]
    _complete_case(test_db, _begin(test_db, MEMBERS[0]))
    # A completed execution with a later failed case verdict still owes its waiver.
    from runtime.api.fixtures.deployment_scoped_qa_run_fixture import (
        record_case_verdict,
    )

    record_case_verdict(test_db, requirement, "fail", evidence=True)
    _waive(test_db, requirement)
    other = _plan(test_db, "other-shared-gate")
    _attach(test_db, MEMBERS[0], other)
    _materialize(test_db, MEMBERS[0])
    assert item_qa_acceptance_blockers(test_db, run_id=RUN, item_id=MEMBERS[0])
    assert not item_qa_acceptance_blockers(test_db, run_id=RUN, item_id=MEMBERS[1])
