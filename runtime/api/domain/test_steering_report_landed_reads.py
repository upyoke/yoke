"""Landed members share QA reads for one report, never across reports."""

from unittest.mock import patch

from runtime.api.domain.qa_capture_pending_review_test_support import _seed_pending
from runtime.api.fixtures.deployment_scoped_qa_run_fixture import (
    create_smoke_plan,
    item_qa_stage_definitions,
    seed_run_standing_on_qa_stage,
)
from runtime.api.fixtures.statement_counter import CountingConnection
from runtime.api.steering_fleet_test_helpers import (
    STEERING_SESSION,
    seed_steering_scope,
)
from yoke_contracts.timestamps import format_instant
from yoke_core.domain.db_helpers import utc_now
from yoke_core.domain.deployment_qa_stage_materialization import (
    materialize_deployment_qa_stage,
)
from yoke_core.domain.steering_fleet_report_compose import (
    combined_dict,
    compose_held_reports,
)


RUN = "run-landed-report"


def _seed(conn):
    seed_steering_scope(conn)
    plan = create_smoke_plan(conn, project="yoke", slug="landed-report-smoke")
    members = tuple(range(7400, 7410))
    seed_run_standing_on_qa_stage(
        conn, run_id=RUN, project="yoke",
        stages=item_qa_stage_definitions(plan), members=members, lineage="e" * 40,
    )
    for member in members:
        materialize_deployment_qa_stage(
            conn, deployment_run_id=RUN, deployment_stage="item-qa",
            deployment_member_item_id=member,
        )
    conn.execute(
        "UPDATE items SET status='release',merged_at=%s,deployment_flow=%s "
        "WHERE id=ANY(%s)",
        (utc_now(), f"flow-{RUN}", list(members)),
    )
    conn.commit()
    return members


def _report(conn, now, compose=compose_held_reports):
    return compose(
        conn, session_id=STEERING_SESSION, now=now, include_inventory=False,
    )


def test_landed_members_share_plan_facts_and_preserve_report(test_db):
    from yoke_core.domain import deployment_qa_member_plans as plans
    from yoke_core.domain import qa_pending_agent_review as pending

    members = _seed(test_db)
    _seed_pending(test_db, "run-review-report", "run")
    now = format_instant(utc_now())
    counted = CountingConnection(test_db)
    with (
        patch.object(plans, "_runs_plan_facts", wraps=plans._runs_plan_facts) as reads,
        patch.object(pending, "_bundle_requirement_ids",
                     wraps=pending._bundle_requirement_ids) as parses,
    ):
        shared = _report(counted, now)
    assert reads.call_count == 2  # One per distinct run, shared by every member.
    assert parses.call_count == 1
    assert len(shared.sections[0].report.landed_open) == len(members)
    baseline = _report(test_db, now, compose_held_reports.__wrapped__)
    assert combined_dict(shared) == combined_dict(baseline)


def test_new_report_observes_changed_member_plan_facts(test_db):
    from yoke_core.domain import deployment_qa_member_plans as plans

    members = _seed(test_db)
    now = format_instant(utc_now())
    with patch.object(plans, "_runs_plan_facts", wraps=plans._runs_plan_facts) as reads:
        before = _report(test_db, now)
        test_db.execute("UPDATE items SET status='done' WHERE id=%s", (members[0],))
        test_db.commit()
        after = _report(test_db, now)
    assert reads.call_count == 2
    assert len(after.sections[0].report.landed_open) == len(members) - 1
    assert combined_dict(before) != combined_dict(after)
