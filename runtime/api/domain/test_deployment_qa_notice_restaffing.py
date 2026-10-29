"""Redispatch reaches a live recipient when a prior QA audience ended."""

from runtime.api.domain.test_deployment_qa_plan_groups import RUN, _seed
from runtime.api.domain.test_deployment_qa_plan_group_scenarios import _dispatch, _form, _manual_plan
from runtime.api.domain.test_deployment_qa_stage_wake_delivery import _project, seed_session
from runtime.api.fixtures.deployment_run_driver_fixture import release_seeded_driver
from yoke_core.domain.deployment_run_driver_attachment import attach_driver, PHASE_EXECUTING


def test_group_dispatch_replaces_notice_to_ended_driver(test_db):
    plan_id = _seed(test_db)
    _manual_plan(test_db, plan_id)
    _project(test_db)
    for session in ("old-driver", "run-starter"):
        seed_session(test_db, session)
    release_seeded_driver(test_db, RUN)
    attach_driver(test_db, RUN, session_id="old-driver", pid=4243, phase=PHASE_EXECUTING)
    test_db.execute("UPDATE deployment_runs SET created_by_session_id='run-starter' WHERE id=%s", (RUN,))
    test_db.commit()
    _form(test_db)
    _dispatch(test_db)
    test_db.execute("UPDATE harness_sessions SET ended_at=now() WHERE session_id='old-driver'")
    test_db.commit()
    _dispatch(test_db)
    rows = test_db.execute(
        "SELECT r.session_id,m.cancelled_at FROM session_messages m "
        "JOIN session_message_recipients r ON r.message_id=m.message_id "
        "WHERE m.idempotency_key LIKE %s ORDER BY m.created_at",
        (f"deployment-qa-stage-wait:{RUN}:item-qa:plan-groups:%",)
    ).fetchall()
    assert len(rows) == 2
    assert rows[0][0] == "old-driver" and rows[0][1] is not None
    assert rows[1][0] == "run-starter" and rows[1][1] is None
    from yoke_core.domain.deployment_qa_stage_wake_state import stalled_qa_notice

    test_db.execute("UPDATE session_message_recipients SET state='acknowledged',"
                    "acknowledged_at=now() WHERE session_id='run-starter'")
    test_db.commit()
    assert not stalled_qa_notice(test_db, RUN, "item-qa")


def test_unanswered_group_with_no_driver_needs_steering_action(test_db):
    from yoke_core.domain.steering_fleet_report_run_progress import run_progress
    from yoke_contracts.timestamps import utc_now
    from yoke_core.domain.deployment_qa_plan_groups import run_groups

    plan_id = _seed(test_db)
    _manual_plan(test_db, plan_id)
    _project(test_db)
    seed_session(test_db, "run-starter")
    release_seeded_driver(test_db, RUN)
    test_db.execute("UPDATE deployment_runs SET created_by_session_id='run-starter' WHERE id=%s", (RUN,))
    test_db.commit()
    _form(test_db)
    _dispatch(test_db)
    (progress,) = run_progress(test_db, project_id=1, now=utc_now())
    assert progress.needs_action and not progress.driver_phase
    (group,) = run_groups(test_db, RUN)
    text = " ".join((*progress.unresolved, *progress.member_lines))
    assert all(str(rid) in text for rid in group.requirement_ids)
    assert "yoke qa plan run --deployment-run-id" in text


def test_member_dispatch_replaces_notice_to_ended_holder(test_db):
    from runtime.api.fixtures.deployment_scoped_qa_run_fixture import seed_member_qa_case
    from runtime.api.domain.test_deployment_qa_stage_wake_delivery import _claim
    from yoke_core.domain.work_claim_targets import make_item_target
    from yoke_core.domain.deployment_qa_stage_dispatch import materialize_and_gate_deployment_qa_stage

    run_id, member = "run-member-restaffed", 9983
    requirement_id = seed_member_qa_case(test_db, run_id=run_id, member_item_id=member)
    test_db.execute(
        "UPDATE qa_requirements SET wake_path='manual', "
        "wake_evidence='a production traffic sample is recorded for this release' WHERE id=%s",
        (requirement_id,),
    )
    test_db.commit()
    _project(test_db)
    for session in ("old-holder", "new-holder"):
        seed_session(test_db, session)
    _claim(test_db, session_id="old-holder", target_kind="item",
           scope_json=make_item_target(member).scope_json())
    stage = {"name": "item-qa", "scope": "item"}
    materialize_and_gate_deployment_qa_stage(test_db, stage, run_id=run_id)
    test_db.execute("UPDATE harness_sessions SET ended_at=now() WHERE session_id='old-holder'")
    test_db.execute("UPDATE work_claims SET released_at=now() WHERE session_id='old-holder'")
    test_db.commit()
    _claim(test_db, session_id="new-holder", target_kind="item",
           scope_json=make_item_target(member).scope_json())
    materialize_and_gate_deployment_qa_stage(test_db, stage, run_id=run_id)
    rows = test_db.execute(
        "SELECT r.session_id,m.cancelled_at FROM session_messages m "
        "JOIN session_message_recipients r ON r.message_id=m.message_id "
        "WHERE m.idempotency_key LIKE %s ORDER BY m.created_at",
        (f"deployment-qa-stage-wait:{run_id}:item-qa:{member}:%",)
    ).fetchall()
    assert len(rows) == 2
    assert rows[0][0] == "old-holder" and rows[0][1] is not None
    assert rows[1][0] == "new-holder" and rows[1][1] is None
