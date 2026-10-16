"""A run's red list names only the failures the run still owes.

Removing a member from a run retracts that member's requirements. The run
stopped grading them at once, but the report kept listing every removed
member's last failure, so a run with one real red read as fourteen.
"""

from __future__ import annotations

from runtime.api.domain.test_steering_fleet_report_deployment_run_facts import (
    STARTED,
    _record_verdict,
    _seed_requirement,
    _seed_run,
)
from runtime.api.steering_fleet_test_helpers import compose, seed_steering_scope
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
