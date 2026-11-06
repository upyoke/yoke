"""Open release QA retains identity, custody and origin across failed takeovers."""

import json

from runtime.api.domain import test_deployment_run_target_takeover as takeover
from runtime.api.domain.test_deployment_qa_successor_receipt import _arrive
from runtime.api.fixtures.deployment_scoped_qa_run_fixture import ITEM_QA_STAGE, record_case_verdict
from yoke_core.domain.deployment_qa_dispatch_preparation import prepare_members
from yoke_core.domain.deployment_run_target_takeover import take_over_waiting_run
from yoke_core.domain.qa_deployment_execution_cleanup import terminal_run_status
from yoke_core.domain.qa_deployment_run_settlement import inherited_qa_sql, settle_unsuccessful_run
from yoke_core.domain.qa_plan_execution_begin import begin_plan_execution


def test_failed_successor_keeps_red_sibling_and_live_execution_for_next_release(test_db, monkeypatch):
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
    test_db.execute("UPDATE deployment_runs SET status='failed' WHERE id=%s", (takeover.NEW,))
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
