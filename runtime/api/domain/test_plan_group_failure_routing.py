"""Failed release groups reach owing holders and the member project's steering."""

import pytest

from runtime.api.domain.test_deployment_qa_plan_group_wait_wakes import _setup
from runtime.api.domain.test_deployment_qa_plan_groups import MEMBERS, RUN, _begin
from runtime.api.domain.test_deployment_qa_stage_wake_delivery import (
    _claim, seed_session, HOLDER_A, HOLDER_B,
)
from runtime.api.fixtures.deployment_run_driver_fixture import DRIVER_SESSION
from yoke_core.domain.deployment_qa_plan_group_dispatch import (
    gate_plan_groups, notify_plan_group_failure, notify_plan_groups_wait,
)
from yoke_core.domain.deployment_qa_plan_group_failure import group_failed
from yoke_core.domain.work_claim_targets import make_steering_target


def _notices(conn):
    return conn.execute(
        "SELECT r.session_id,m.body FROM session_messages m "
        "JOIN session_message_recipients r ON r.message_id=m.message_id "
        "WHERE m.idempotency_key LIKE %s OR m.idempotency_key LIKE %s ORDER BY r.session_id",
        (f"deployment-qa-plan-group-failure:{RUN}:%", f"%{RUN}%failure-%"),
    ).fetchall()


@pytest.mark.parametrize("outcome", ["blocked", "rejected", "aborted"])
def test_failure_routes_once_per_owing_member_after_a_wait_notice(test_db, outcome):
    group = _setup(test_db, manual=False)
    # A carried member's fallback must use its own project, not the run's.
    test_db.execute("UPDATE items SET project_id=2 WHERE id=%s", (MEMBERS[-1],))
    seed_session(test_db, "member-steering")
    _claim(test_db, session_id="member-steering", target_kind="steering",
           scope_json=make_steering_target(2).scope_json())
    test_db.commit()
    notify_plan_groups_wait(test_db, run_id=RUN, stage_name="item-qa", groups=[group],
                            project_id=1, item_refs=str)
    if outcome == "aborted":
        execution = _begin(test_db)
        test_db.execute("UPDATE qa_plan_executions SET state='aborted' WHERE id=%s",
                        (execution["id"],))
        test_db.commit()
    assert group_failed(test_db, group, {"outcome": outcome})
    for _ in range(2):
        notify_plan_group_failure(test_db, run_id=RUN, stage_name="item-qa", group=group,
                                 project_id=1, reasons=[outcome], item_refs=str)
    notices = _notices(test_db)
    assert sorted(row[0] for row in notices) == sorted(
        [HOLDER_A, HOLDER_B, "member-steering", DRIVER_SESSION]
    )
    for recipient, body in notices:
        if recipient == DRIVER_SESSION:
            assert all(f"routed to {member} holder" in body for member in MEMBERS)
        else:
            assert all(str(rid) in body for rid in group.requirement_ids)
            assert "qa plan run" in body


def test_aborted_attempt_with_a_live_retry_sends_nothing(test_db):
    group = _setup(test_db, manual=False)
    execution = _begin(test_db)
    test_db.execute("UPDATE qa_plan_executions SET state='aborted' WHERE id=%s",
                    (execution["id"],))
    test_db.commit()
    _begin(test_db)
    assert not group_failed(test_db, group, {"outcome": "waiting"})
    gate_plan_groups(test_db, {"scope": "item", "name": "item-qa"}, run_id=RUN,
                     project_id=1, item_refs=str)
    assert _notices(test_db) == []


def test_dispatch_and_settlement_route_resultless_abort(test_db):
    from yoke_core.domain.deployment_qa_plan_group_writes import group_subject
    from yoke_core.domain.deployment_qa_stage_settlement import settle_plan_group

    group = _setup(test_db, manual=False)
    execution = _begin(test_db)
    test_db.execute("UPDATE qa_plan_executions SET state='aborted' WHERE id=%s", (execution["id"],))
    test_db.commit()
    gate_plan_groups(test_db, {"scope": "item", "name": "item-qa"}, run_id=RUN,
                     project_id=1, item_refs=str)
    assert len(_notices(test_db)) == len(MEMBERS) + 1
    before = list(_notices(test_db))
    subject = group_subject(test_db, RUN, "item-qa", group, require_active=True)
    settle_plan_group(test_db, subject)
    assert len(_notices(test_db)) == len(before)
