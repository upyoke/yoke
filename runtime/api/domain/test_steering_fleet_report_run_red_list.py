"""A run's red list names only the failures the run still owes.

Removing a member from a run retracts that member's requirements. The run
stopped grading them at once, but the report kept listing every removed
member's last failure, so a run with one real red read as fourteen.
"""

from __future__ import annotations

import json

from runtime.api.domain.steering_fleet_report_deployment_run_facts_test_support import (
    STAGE_RELEASE,
    STARTED,
    _record_verdict,
    _seed_requirement,
    _seed_run,
)
from runtime.api.steering_fleet_test_helpers import compose, seed_steering_scope
from yoke_core.domain.steering_fleet_report_compose import (
    CombinedFleetReport,
    ScopedFleetReport,
)
from yoke_core.domain.steering_fleet_report_headline import headline_line
from yoke_core.domain.steering_fleet_report_render import report_body


RUN_ID = "run-20260826-040"


def _retract(conn, requirement_id: int) -> None:
    conn.execute(
        "UPDATE qa_requirements SET retracted_at=%s WHERE id=%s",
        (STARTED, requirement_id),
    )


def test_a_retracted_red_requirement_leaves_the_run_red_list(test_db) -> None:
    conn = seed_steering_scope(test_db)
    _seed_run(conn, run_id=RUN_ID)
    _seed_requirement(conn, run_id=RUN_ID, requirement_id=941, member_item_id=None)
    _seed_requirement(conn, run_id=RUN_ID, requirement_id=942, member_item_id=1)
    _seed_requirement(conn, run_id=RUN_ID, requirement_id=943, member_item_id=2)
    for requirement_id in (941, 942, 943):
        _record_verdict(conn, requirement_id=requirement_id, verdict="fail")
    _retract(conn, 942)
    _retract(conn, 943)
    conn.commit()

    report = compose(conn)
    run = report.deployment_runs[0]

    assert [red.requirement_id for red in run.red] == [941]
    assert run.total_blocking == 1
    body = report_body(report)
    assert "#941" in body
    assert "#942" not in body and "#943" not in body


SUPERSEDING_RUN = "run-20261120-020"


def test_superseding_run_with_only_stale_fails_needs_no_decision(test_db) -> None:
    """Run-020 carried run-016's fail; the fail named run-016's target."""
    conn = seed_steering_scope(test_db)
    _seed_run(conn, run_id=SUPERSEDING_RUN, stage=STAGE_RELEASE)
    _seed_requirement(conn, run_id=SUPERSEDING_RUN, requirement_id=951, member_item_id=1)
    conn.execute(
        "UPDATE qa_requirements SET execution_target_digest=%s WHERE id=951",
        ("179da860" * 8,),
    )
    conn.execute(
        "INSERT INTO qa_runs(qa_requirement_id,performed_by,qa_kind,verdict,"
        "raw_result,started_at,created_at,completed_at) "
        "VALUES (951,'agent','browser','fail',%s,%s,%s,%s)",
        (json.dumps({"execution_target_digest": "b50fdeaa" * 8}),) + (STARTED,) * 3,
    )
    conn.commit()

    report = compose(conn)
    run = report.deployment_runs[0]

    assert run.red == ()
    assert not run.needs_action
    assert report.runs_needing_action() == ()
    assert f"! {SUPERSEDING_RUN}" not in report_body(report)
    headline = headline_line(
        CombinedFleetReport(report.composed_at, (ScopedFleetReport("yoke", report),)),
        {},
    )
    assert "needing a decision" not in headline
