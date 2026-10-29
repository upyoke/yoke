"""Redispatch reaches a live recipient when a prior QA audience ended."""

from runtime.api.domain.test_deployment_qa_plan_groups import RUN, _seed
from runtime.api.domain.test_deployment_qa_plan_group_scenarios import _dispatch, _form
from runtime.api.domain.test_deployment_qa_stage_wake_delivery import _project, seed_session
from runtime.api.fixtures.deployment_run_driver_fixture import release_seeded_driver
from yoke_core.domain.deployment_run_driver_attachment import attach_driver, PHASE_EXECUTING


def test_group_dispatch_replaces_notice_to_ended_driver(test_db):
    _seed(test_db)
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
