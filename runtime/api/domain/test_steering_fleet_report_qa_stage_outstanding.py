"""A QA stage's outstanding count is the gate's, not the completion reader's.

The measured miss: three item-qa members still owed evidence — two with no
pinned cases, one with no execution and no materialized cases — while the
report printed ``0 of 3 outstanding`` and told the seat to re-drive. That
count came from settled ``qa_requirements`` rows. The stage gate does not.
"""

from __future__ import annotations

from runtime.api.fixtures.deployment_scoped_qa_run_fixture import (
    ITEM_QA_STAGE,
    item_qa_stage_definitions,
    seed_run_standing_on_qa_stage,
)
from runtime.api.steering_fleet_test_helpers import compose, seed_steering_scope
from yoke_core.domain.db_helpers import iso8601_now
from yoke_core.domain.deployment_run_completion_preconditions import (
    blocking_obligation_total,
    unresolved_blocking_qa,
)
from yoke_core.domain.post_deploy_verification_answer import (
    cases_not_selected_refusal,
)
from yoke_core.domain.steering_fleet_report_render import report_body


RUN_ID = "run-20260920-007"
NO_CASES_MEMBERS = (3459, 3461)
GATE_MEMBER = 3467
MEMBERS = (*NO_CASES_MEMBERS, GATE_MEMBER)
LINEAGE = "c" * 40


def _passed_requirement(
    conn, *, requirement_id: int, member_item_id: int | None, method_id: str | None
) -> None:
    now = iso8601_now()
    conn.execute(
        "INSERT INTO qa_requirements("
        "id,deployment_run_id,deployment_stage,deployment_member_item_id,"
        "qa_kind,qa_phase,blocking_mode,requirement_source,method_id,created_at"
        ") VALUES (%s,%s,%s,%s,'browser','post_deploy','blocking',"
        "'flow_derived',%s,%s)",
        (
            requirement_id,
            RUN_ID,
            ITEM_QA_STAGE,
            member_item_id,
            method_id,
            now,
        ),
    )
    conn.execute(
        "INSERT INTO qa_runs("
        "qa_requirement_id,performed_by,qa_kind,verdict,created_at,completed_at"
        ") VALUES (%s,'agent','browser','pass',%s,%s)",
        (requirement_id, now, now),
    )


def test_a_qa_stage_reports_the_gate_not_the_settled_requirement_count(test_db) -> None:
    conn = seed_steering_scope(test_db)
    seed_run_standing_on_qa_stage(
        conn,
        run_id=RUN_ID,
        project="yoke",
        stages=item_qa_stage_definitions(None),
        members=MEMBERS,
        lineage=LINEAGE,
    )
    # Three passing blocking rows: the completion reader calls that
    # "0 of 3 outstanding". The gate still waits on every member.
    _passed_requirement(conn, requirement_id=9101, member_item_id=None, method_id=None)
    _passed_requirement(conn, requirement_id=9102, member_item_id=None, method_id=None)
    _passed_requirement(
        conn, requirement_id=9103, member_item_id=GATE_MEMBER, method_id="command"
    )
    conn.commit()

    assert unresolved_blocking_qa(conn, RUN_ID) == []
    assert blocking_obligation_total(conn, RUN_ID) == 3

    report = compose(conn, now=iso8601_now())
    body = report_body(report)
    run = report.deployment_runs[0]

    assert run.run_id == RUN_ID
    assert run.stage == ITEM_QA_STAGE
    assert run.outstanding == 3
    assert run.total_blocking == 3
    assert run.needs_action is False
    assert f"{RUN_ID}" in body
    assert "3 of 3 outstanding" in body
    assert f"Nothing is outstanding; re-drive {RUN_ID}" not in body
    refusal = cases_not_selected_refusal()
    for member in NO_CASES_MEMBERS:
        assert f"member {member}: {refusal}" in body
    assert f"member {GATE_MEMBER}: no completed scoped QA execution exists" in body
    assert f"member {GATE_MEMBER}: no concrete QA cases are materialized" in body
