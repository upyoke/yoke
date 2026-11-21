"""A carried walk keeps its member while a correction landing is open."""

import pytest

from runtime.api.domain import deployment_run_target_takeover_test_support as takeover
from runtime.api.domain.merge_queue_observer_test_helpers import open_unarmed
from runtime.api.fixtures.deployment_scoped_qa_run_fixture import ITEM_QA_STAGE
from yoke_core.domain import deployment_landing_guard
from yoke_core.domain.deployment_qa_execution_target import (
    validate_deployment_execution_target,
)
from yoke_core.domain.deployment_run_member_set_aside import (
    SET_ASIDE_REASON,
    set_aside_reworking_members,
)
from yoke_core.domain.deployment_run_membership_removals import membership_removals
from yoke_core.domain.merge_queue_landing_attempt import record_attempt
from yoke_core.domain.qa_plan_execution_begin import begin_plan_execution
from yoke_core.domain.qa_plan_execution_lifecycle import finish_plan_execution
from yoke_core.domain.qa_plan_execution_store import select_plan_execution


def test_reworking_member_stays_attached_until_carried_walk_ends(test_db, monkeypatch):
    member = takeover.WAITING
    requirements = takeover._seed_old(test_db, run_qa=False)
    takeover._close_passed(test_db)
    execution = begin_plan_execution(
        test_db,
        deployment_run_id=takeover.OLD,
        deployment_stage=ITEM_QA_STAGE,
        deployment_member_item_id=member,
        actor_id="1",
        session_id=takeover.DRIVER_SESSION,
    )
    execution_id = execution["id"]
    finish_plan_execution(test_db, execution, state="walking", reason="walk started")
    takeover._seed_new(test_db)
    takeover._contains(monkeypatch)
    assert takeover._take_over(test_db) == takeover.OLD

    run = takeover.NEW
    record_attempt(test_db, member, "43", enqueued_at=None)
    monkeypatch.setattr(deployment_landing_guard, "read_pr_landing_state", open_unarmed)
    for _ in range(2):
        assert set_aside_reworking_members(test_db, run, [member]) == {}
        test_db.commit()
        assert takeover._members(test_db, run) == {member}

    execution = select_plan_execution(test_db, execution_id, lock=False)
    assert execution["state"] == "walking"
    assert execution["deployment_run_id"] == run
    assert execution["execution_target"]["deployment"]["run_id"] == takeover.OLD
    validate_deployment_execution_target(test_db, execution)
    with pytest.raises(ValueError, match="item_landing_open:.*#43"):
        deployment_landing_guard.require_closed_landing(test_db, member)

    finish_plan_execution(test_db, execution, state="aborted", reason="walk stopped")
    assert set_aside_reworking_members(test_db, run, [member]).keys() == {member}
    test_db.commit()
    assert takeover._members(test_db, run) == set()
    (removal,) = membership_removals(test_db, run)
    assert removal["reason"] == SET_ASIDE_REASON
    assert select_plan_execution(test_db, execution_id, lock=False)["state"] == "aborted"
    saved = test_db.execute(
        "SELECT retracted_at FROM qa_requirements WHERE id=%s", (requirements[member],)
    ).fetchone()
    assert saved is not None and saved["retracted_at"] is None
