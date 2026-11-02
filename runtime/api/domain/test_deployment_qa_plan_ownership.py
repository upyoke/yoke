"""Single-member plans stay with member QA while shared plans stay with the driver."""

from runtime.api.domain.test_deployment_qa_plan_groups import (
    MEMBERS,
    RUN,
    SLUG,
    _attach,
    _seed,
)
from runtime.api.domain.test_deployment_qa_stage_execution import _complete_case, _plan
from yoke_core.domain.deployment_qa_plan_group_writes import ensure_groups
from yoke_core.domain.deployment_qa_plan_groups import run_groups
from yoke_core.domain.deployment_qa_plan_ownership import plan_owners
from yoke_core.domain.deployment_qa_stage_materialization import (
    materialize_deployment_qa_stage,
)
from yoke_core.domain.deployment_run_stage_entry import set_current_stage
from yoke_core.domain.qa_plan_execution_state import begin_plan_execution


def _mixed(conn):
    shared = _seed(conn)
    single = _plan(conn, "single-smoke")
    _attach(conn, MEMBERS[0], single)
    set_current_stage(conn, RUN, "item-qa")
    conn.commit()
    return shared, single


def test_dispatch_keeps_single_plan_out_of_driver_capture_and_wakes_holder(test_db):
    from yoke_core.domain.deployment_qa_stage_dispatch import (
        materialize_and_gate_deployment_qa_stage,
    )
    from runtime.api.domain.test_deployment_qa_stage_wake_delivery import (
        HOLDER_A,
        _claim,
        _project,
        seed_session,
    )
    from yoke_core.domain.deployment_qa_pending_plans import pending_stage_plans
    from yoke_core.domain.work_claim_targets import make_item_target

    shared, single = _mixed(test_db)
    _project(test_db)
    seed_session(test_db, HOLDER_A)
    _claim(
        test_db,
        session_id=HOLDER_A,
        target_kind="item",
        scope_json=make_item_target(MEMBERS[0]).scope_json(),
    )
    test_db.commit()
    rc, message = materialize_and_gate_deployment_qa_stage(
        test_db,
        {"scope": "item", "name": "item-qa"},
        run_id=RUN,
    )
    assert rc == -4, message
    assert {group.plan_id for group in run_groups(test_db, RUN)} == {shared}
    pending = pending_stage_plans(test_db, {"scope": "item", "name": "item-qa"}, RUN)
    assert {row["plan"] for row in pending} == {SLUG}
    notices = test_db.execute(
        "SELECT m.body FROM session_messages m JOIN session_message_recipients r "
        "ON r.message_id=m.message_id WHERE r.session_id=%s",
        (HOLDER_A,),
    ).fetchall()
    assert notices and any(
        "qa plan run" in row[0] and "--item" in row[0] for row in notices
    )
    execution = begin_plan_execution(
        test_db,
        deployment_run_id=RUN,
        deployment_stage="item-qa",
        deployment_member_item_id=MEMBERS[0],
        actor_id="2",
        session_id=HOLDER_A,
    )
    assert execution["deployment_member_item_id"] == MEMBERS[0]
    assert {row["plan_id"] for row in execution["roster"]} == {single}
    _complete_case(test_db, execution)
    assert plan_owners(test_db, RUN) == {shared: None, single: MEMBERS[0]}


def test_late_attachment_keeps_ownership_pinned_before_first_dispatch(test_db):
    shared, single = _mixed(test_db)
    _attach(test_db, MEMBERS[1], single)
    test_db.execute(
        "DELETE FROM qa_plan_item_attachments WHERE item_id=%s AND plan_id=%s",
        (MEMBERS[-1], shared),
    )
    test_db.commit()
    ensure_groups(test_db, RUN, "item-qa")
    assert plan_owners(test_db, RUN) == {shared: None, single: MEMBERS[0]}
    assert {group.plan_id for group in run_groups(test_db, RUN)} == {shared}
    for member in MEMBERS[:2]:
        materialize_deployment_qa_stage(
            test_db,
            deployment_run_id=RUN,
            deployment_stage="item-qa",
            deployment_member_item_id=member,
        )
    rows = test_db.execute(
        "SELECT DISTINCT deployment_member_item_id FROM qa_requirements "
        "WHERE deployment_run_id=%s AND plan_id=%s",
        (RUN, single),
    ).fetchall()
    assert {row[0] for row in rows} == set(MEMBERS[:2])


def test_single_member_plan_settles_and_credits_its_item(test_db, monkeypatch):
    from yoke_core.domain import deployment_item_completion_runs as completion
    from yoke_core.domain.deployment_qa_plan_credit import plan_credit_misses
    from yoke_core.domain.deployment_qa_run_acceptance import current_item_qa

    single = _seed(test_db, attached=MEMBERS[:1])
    set_current_stage(test_db, RUN, "item-qa")
    test_db.commit()
    ensure_groups(test_db, RUN, "item-qa")
    test_db.commit()
    monkeypatch.setattr(
        completion, "latest_qa_member_run", lambda conn, **_: {"id": RUN}
    )
    assert plan_credit_misses(test_db, MEMBERS[0])
    assert run_groups(test_db, RUN) == []
    materialize_deployment_qa_stage(
        test_db,
        deployment_run_id=RUN,
        deployment_stage="item-qa",
        deployment_member_item_id=MEMBERS[0],
    )
    execution = begin_plan_execution(
        test_db,
        deployment_run_id=RUN,
        deployment_stage="item-qa",
        deployment_member_item_id=MEMBERS[0],
        actor_id="2",
        session_id="single-owner",
    )
    assert {row["plan_id"] for row in execution["roster"]} == {single}
    _complete_case(test_db, execution)
    standing = current_item_qa(
        test_db, run_id=RUN, item_id=MEMBERS[0], current_stage="item-qa"
    )
    assert standing.accepted
    assert plan_credit_misses(test_db, MEMBERS[0]) == []
