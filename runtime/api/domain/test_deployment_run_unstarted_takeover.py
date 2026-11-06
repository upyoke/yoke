"""Unstarted releases transfer memberships, obligations and live QA intact."""

import pytest
from runtime.api.domain.deployment_run_target_takeover_test_support import (
    _seed_old, _seed_new, _contains, _take_over, _members, _run,
    OLD, NEW, PASSED, WAITING,
)
from yoke_core.domain.qa_plan_execution_begin import begin_plan_execution
from yoke_core.domain.qa_plan_execution_store import select_plan_execution
from runtime.api.fixtures.deployment_run_driver_fixture import DRIVER_SESSION


@pytest.mark.parametrize("lineage", [None, "b" * 40])
def test_created_predecessor_transfers_members_and_live_qa(test_db, monkeypatch, lineage):
    cases = _seed_old(test_db, run_qa=False)
    execution = begin_plan_execution(test_db, deployment_run_id=OLD,
        deployment_stage="item-qa", deployment_member_item_id=WAITING,
        actor_id="1", session_id=DRIVER_SESSION)
    before = select_plan_execution(test_db, execution["id"], lock=False)
    test_db.execute("UPDATE deployment_runs SET status='created',release_lineage=%s WHERE id=%s",
                    (lineage, OLD))
    _seed_new(test_db)
    _contains(monkeypatch)
    assert _take_over(test_db) == OLD
    assert _run(test_db, OLD)["status"] == "cancelled"
    assert _members(test_db, OLD) == set()
    assert _members(test_db, NEW) == {PASSED, WAITING}
    assert select_plan_execution(test_db, execution["id"], lock=False) == {**before, "deployment_run_id": NEW}
    rows = test_db.execute("SELECT deployment_run_id,retracted_at FROM qa_requirements WHERE id=ANY(%s)",
                           (list(cases.values()),)).fetchall()
    assert all(row[0] == NEW and row[1] is None for row in rows)


def test_set_aside_qa_is_adopted_by_next_enrolling_run(test_db, monkeypatch):
    from yoke_core.domain.deployment_run_member_set_aside import set_aside_reworking_members
    from yoke_core.domain.deployment_run_set_aside_qa import adopt_set_aside_qa
    from yoke_core.domain.merge_queue_landing_attempt import record_attempt
    from yoke_core.domain import deployment_landing_guard as guard
    from runtime.api.domain.merge_queue_observer_test_helpers import open_unarmed

    cases = _seed_old(test_db, run_qa=False)
    execution = begin_plan_execution(test_db, deployment_run_id=OLD,
        deployment_stage="item-qa", deployment_member_item_id=WAITING,
        actor_id="1", session_id=DRIVER_SESSION)
    before = select_plan_execution(test_db, execution["id"], lock=False)
    record_attempt(test_db, WAITING, "43", enqueued_at=None)
    monkeypatch.setattr(guard, "read_pr_landing_state", open_unarmed)
    assert set_aside_reworking_members(test_db, OLD, [WAITING])
    test_db.commit()
    assert _members(test_db, OLD) == {PASSED}
    assert select_plan_execution(test_db, execution["id"], lock=False) == before
    row = test_db.execute("SELECT retracted_at FROM qa_requirements WHERE id=%s", (cases[WAITING],)).fetchone()
    assert row[0] is None
    from yoke_core.domain.qa_deployment_run_settlement import settle_unsuccessful_run
    from yoke_core.domain.qa_deployment_execution_cleanup import terminal_run_status

    test_db.execute("UPDATE deployment_runs SET status='cancelled' WHERE id=%s", (OLD,))
    settle_unsuccessful_run(test_db, OLD, reason="old run ended")
    test_db.commit()
    assert terminal_run_status(test_db, before) is None
    assert select_plan_execution(test_db, execution["id"], lock=False) == before
    assert test_db.execute("SELECT retracted_at FROM qa_requirements WHERE id=%s", (cases[WAITING],)).fetchone()[0] is None
    _seed_new(test_db)
    adopt_set_aside_qa(test_db, NEW, [WAITING])
    assert select_plan_execution(test_db, execution["id"], lock=False) == {**before, "deployment_run_id": NEW}
    assert test_db.execute("SELECT deployment_run_id FROM qa_requirements WHERE id=%s", (cases[WAITING],)).fetchone()[0] == NEW
