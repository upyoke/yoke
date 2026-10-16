"""Delivery members credit their own scoped QA evidence."""

from __future__ import annotations

from runtime.api.domain.test_deployment_delivery_close_out_notice import (
    COMPLETION_FLOW,
    _member_at_release_wait,
    _project,
)
from runtime.api.domain.test_deployment_qa_stage_wake_delivery import HOLDER_A
from runtime.api.domain.test_no_obligation_member_close_out import _ready_member
from runtime.api.domain.test_run_success_member_settlement import (
    FIRST_ITEM,
    SECOND_ITEM,
    _executing_run,
)

from runtime.api.domain.test_dash_post_deploy_done_consumption import _bind_original
from yoke_core.domain.deployment_qa_source_obligation import source_obligation_consumed
from runtime.api.fixtures.backlog_inserts import insert_qa_requirement, insert_qa_run
from yoke_core.domain.db_helpers import iso8601_now
from yoke_core.domain.deployment_flow_policy import (
    RELEASE_POLICY_SCHEMA_VERSION,
)

from yoke_core.domain.no_obligation_member_close_out import satisfied_delivery_member


def _member_run(conn, run_id, members):
    conn.execute(
        "INSERT INTO deployment_flows "
        "(id,project_id,name,stages,created_at,definition_schema_version) "
        "VALUES (%s,1,%s,'[]',%s,%s)",
        (
            COMPLETION_FLOW,
            COMPLETION_FLOW,
            iso8601_now(),
            RELEASE_POLICY_SCHEMA_VERSION,
        ),
    )
    _executing_run(conn, run_id, members)


def _requirement(conn, run_id, *, member=None, verdict=None):
    requirement_id = insert_qa_requirement(
        conn,
        item_id=None,
        deployment_run_id=run_id,
        deployment_member_item_id=member,
        deployment_stage="item-qa" if member is not None else None,
        qa_kind="method_case",
        qa_phase="post_deploy",
        blocking_mode="blocking",
    )["id"]
    if verdict is not None:
        insert_qa_run(
            conn,
            qa_requirement_id=requirement_id,
            qa_kind="method_case",
            verdict=verdict,
        )
    return requirement_id


def test_scoped_run_requires_the_members_own_qa(test_db):
    _project(test_db)
    for item_id in (FIRST_ITEM, SECOND_ITEM):
        _member_at_release_wait(test_db, item_id)
    run_id = "run-scoped-exact-member"
    _member_run(test_db, run_id, (FIRST_ITEM, SECOND_ITEM))
    test_db.commit()
    _requirement(test_db, run_id, verdict="pass")
    _requirement(test_db, run_id, member=SECOND_ITEM, verdict="pass")
    assert not satisfied_delivery_member(test_db, item_id=FIRST_ITEM, run_id=run_id)
    own_id = _requirement(test_db, run_id, member=FIRST_ITEM)
    assert not satisfied_delivery_member(test_db, item_id=FIRST_ITEM, run_id=run_id)
    insert_qa_run(test_db, qa_requirement_id=own_id, verdict="pass")
    assert satisfied_delivery_member(test_db, item_id=FIRST_ITEM, run_id=run_id)


def test_scoped_run_does_not_credit_run_wide_source(test_db):
    _project(test_db)
    _ready_member(test_db, FIRST_ITEM, HOLDER_A)
    source_id = _bind_original(test_db, item_id=FIRST_ITEM)
    run_id = "run-scoped-source-run-wide"
    _member_run(test_db, run_id, (FIRST_ITEM,))
    _requirement(test_db, run_id, verdict="pass")
    test_db.execute(
        "UPDATE deployment_runs SET status='succeeded' WHERE id=%s", (run_id,)
    )
    test_db.commit()
    assert not source_obligation_consumed(
        test_db, item_id=FIRST_ITEM, source_requirement_id=source_id
    )
