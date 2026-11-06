"""Open release QA retains identity, custody and origin across failed takeovers."""

import json

import pytest

from runtime.api.domain import test_deployment_run_target_takeover as takeover
from runtime.api.domain.test_deployment_qa_successor_receipt import _arrive
from runtime.api.fixtures.deployment_scoped_qa_run_fixture import ITEM_QA_STAGE, record_case_verdict
from yoke_core.domain.deployment_qa_dispatch_preparation import prepare_members
from yoke_core.domain.deployment_run_target_takeover import take_over_waiting_run
from yoke_core.domain.qa_deployment_execution_cleanup import terminal_run_status
from yoke_core.domain.qa_deployment_run_settlement import inherited_qa_sql, settle_unsuccessful_run
from yoke_core.domain.qa_plan_execution_begin import begin_plan_execution


@pytest.mark.parametrize("settling", [False, True])
def test_failed_successor_keeps_red_sibling_and_live_execution_for_next_release(test_db, monkeypatch, settling):
    cases = takeover._seed_old(test_db, run_qa=False)
    timing, red = cases[takeover.WAITING], cases[takeover.PASSED]
    test_db.execute("UPDATE qa_requirements SET wake_path='manual',wake_evidence='two release receipts exist' WHERE id=%s", (timing,))
    record_case_verdict(test_db, red, "fail", evidence=True)
    execution = begin_plan_execution(
        test_db, deployment_run_id=takeover.OLD, deployment_stage=ITEM_QA_STAGE,
        deployment_member_item_id=takeover.WAITING, actor_id="1",
        session_id=takeover.DRIVER_SESSION,
    )
    takeover._seed_new(test_db)
    takeover._contains(monkeypatch)
    assert takeover._take_over(test_db) == takeover.OLD
    _arrive(test_db, ready=True)
    test_db.execute("UPDATE deployment_runs SET current_stage=%s WHERE id=%s", (ITEM_QA_STAGE, takeover.NEW))
    test_db.commit()
    assert prepare_members(test_db, {"name": ITEM_QA_STAGE}, run_id=takeover.NEW, members=[takeover.WAITING, takeover.PASSED]) == {}
    target = json.loads(test_db.execute("SELECT execution_target_json FROM qa_requirements WHERE id=%s", (timing,)).fetchone()[0])
    assert target["deployment"]["run_id"] == takeover.NEW
    assert target["deployment"]["starting_run_id"] == takeover.OLD
    assert test_db.execute(f"SELECT ({inherited_qa_sql()}) FROM qa_requirements WHERE id=%s", (timing,)).fetchone()[0]
    test_db.execute("UPDATE deployment_runs SET status='failed',settling_at=CASE WHEN %s THEN now() ELSE NULL END WHERE id=%s", (settling, takeover.NEW))
    assert settle_unsuccessful_run(test_db, takeover.NEW, reason="driver failed")
    assert terminal_run_status(test_db, {"deployment_run_id": takeover.NEW}) is None
    test_db.commit()
    from yoke_core.domain.deploy_target_occupancy import occupancies, run_target

    assert occupancies(test_db, run_target(test_db, takeover.NEW).origins) == []
    assert test_db.execute("SELECT state FROM qa_plan_executions WHERE id=%s", (execution["id"],)).fetchone()[0] == "active"
    assert test_db.execute("SELECT count(*) FROM qa_requirements WHERE id=ANY(%s) AND retracted_at IS NULL", (list(cases.values()),)).fetchone()[0] == 2
    next_run = "run-takeover-next"
    test_db.execute(
        "INSERT INTO deployment_runs(id,project_id,flow,target_tier,target_environment_id,release_lineage,status,created_at) "
        "SELECT %s,project_id,flow,target_tier,target_environment_id,%s,'created',created_at FROM deployment_runs WHERE id=%s",
        (next_run, "d" * 40, takeover.NEW),
    )
    # A reopened member is already admitted; takeover preserves that admission.
    test_db.execute("UPDATE items SET status='implementing' WHERE id=%s", (takeover.WAITING,))
    test_db.commit()
    assert take_over_waiting_run(test_db, next_run, session_id=takeover.DRIVER_SESSION, actor_id=1) == takeover.NEW
    test_db.commit()
    assert takeover._members(test_db, next_run) == {takeover.WAITING, takeover.PASSED}
    assert test_db.execute("SELECT deployment_run_id FROM qa_plan_executions WHERE id=%s", (execution["id"],)).fetchone()[0] == next_run
    rows = test_db.execute("SELECT id,retracted_at FROM qa_requirements WHERE deployment_run_id=%s AND id=ANY(%s)", (next_run, list(cases.values()))).fetchall()
    assert {row[0] for row in rows} == set(cases.values())
    assert all(row[1] is None for row in rows)
    assert test_db.execute("SELECT count(*) FROM qa_runs WHERE qa_requirement_id=%s AND verdict='fail'", (red,)).fetchone()[0] == 1


@pytest.mark.parametrize("status", ["implementing", "reviewing-implementation"])
@pytest.mark.parametrize("predecessor_status", ["executing", "failed"])
def test_create_preserves_reopened_member_admission_and_qa(
    test_db, monkeypatch, status, predecessor_status
):
    from runtime.api.domain import test_deployment_run_create_takeover_enrollment as creation

    execution_id = creation._seed(test_db, monkeypatch, flow=None)
    test_db.execute("UPDATE items SET status=%s WHERE id=%s", (status, takeover.WAITING))
    test_db.execute("UPDATE deployment_runs SET status=%s WHERE id=%s", (predecessor_status, takeover.OLD))
    test_db.commit()
    before = creation._qa_rows(test_db)

    created = creation._create()

    assert takeover._members(test_db, created) == {takeover.PASSED, takeover.WAITING, creation.BLOCKER}
    assert creation._qa_rows(test_db, created) == before
    assert test_db.execute("SELECT deployment_run_id FROM qa_plan_executions WHERE id=%s", (execution_id,)).fetchone()[0] == created
    assert test_db.execute("SELECT count(*) FROM qa_requirements WHERE deployment_run_id=%s AND retracted_at IS NOT NULL", (created,)).fetchone()[0] == 0


def test_frozen_carried_member_outside_history_is_set_aside(test_db, tmp_path, monkeypatch):
    from runtime.api.domain import test_deployment_run_reopened_member_set_aside as frozen
    from yoke_core.domain.deployment_run_membership_removals import record_membership_removals
    from yoke_core.domain.deployment_runs_validation import cmd_validate_composition

    frozen._frozen_run_with_reopened_member(test_db, tmp_path, monkeypatch, reopened_sha="correction", settled=True)
    predecessor = "run-carried-predecessor"
    test_db.execute(
        "INSERT INTO deployment_runs(id,project_id,flow,status,created_at) "
        "SELECT %s,project_id,flow,'cancelled',created_at FROM deployment_runs WHERE id=%s",
        (predecessor, frozen.RUN),
    )
    test_db.execute("UPDATE deployment_runs SET supersedes_run_id=%s WHERE id=%s", (predecessor, frozen.RUN))
    record_membership_removals(
        test_db, predecessor, [frozen.REOPENED], reason="QA transferred",
        session_id=None, actor_id=None, transferred_to_run_id=frozen.RUN,
    )
    test_db.commit()

    ok, message = cmd_validate_composition(frozen.RUN)

    assert ok, message
    assert "Set aside reopened members awaiting a later release" in message
    assert frozen._members(test_db) == {frozen.SIBLING}
