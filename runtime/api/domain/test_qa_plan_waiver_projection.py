"""Postgres plan projections retain waivers without reviving retired proof."""

from __future__ import annotations

import pytest

from runtime.api.domain.test_qa_simulation_triage import _record, _seed
from runtime.api.fixtures.backlog_inserts import insert_item
from runtime.api.fixtures.backlog_qa_inserts import insert_qa_requirement, insert_qa_run
from yoke_core.domain.events_acting_identity import acting_event_identity
from yoke_core.domain.qa_catalog_reads import list_plans
from yoke_core.domain.qa_plan_case_proof import _case_result
from yoke_core.domain.qa_plan_detail import get_plan
from yoke_core.domain.qa_plan_management import create_plan, replace_plan_cases
from yoke_core.domain.qa_requirement_ops import waive_requirement

CASE_KEY = "command"


def _plan(conn):
    item = insert_item(conn, title="Plan waiver projection")
    plan = create_plan(
        conn, project="yoke", slug="waiver-projection", name="Waiver projection"
    )
    plan_id = int(plan["id"])
    replace_plan_cases(
        conn,
        plan_id=plan_id,
        cases=[
            {
                "case_key": CASE_KEY,
                "position": 1,
                "method_id": "command",
                "instructions": "Run the command.",
                "expected_outcome": "The command passes or is explicitly waived.",
                "method_config": {"command": "true"},
            }
        ],
    )
    return int(item["id"]), plan_id


def _requirement(conn, item_id, plan_id, **kwargs):
    return int(
        insert_qa_requirement(
            conn,
            item_id=item_id,
            plan_id=plan_id,
            plan_case_key=CASE_KEY,
            method_id="command",
            qa_kind="plan_case",
            **kwargs,
        )["id"]
    )


def _waive(conn, requirement_id):
    waive_requirement(
        conn, requirement_id, "Operator accepts the case", source="operator", force=True
    )


def _listed(conn, plan_id):
    return next(row for row in list_plans(conn, project="yoke") if row["id"] == plan_id)


@pytest.mark.parametrize("after_failure", [False, True])
def test_waiver_is_visible_in_plan_detail_and_list_without_another_attempt(
    test_db, after_failure
):
    item_id, plan_id = _plan(test_db)
    requirement_id = _requirement(test_db, item_id, plan_id)
    run_id = None
    if after_failure:
        run_id = int(
            insert_qa_run(
                test_db,
                qa_requirement_id=requirement_id,
                verdict="fail",
                verdict_reason="Actual newest failure",
                started_at="2026-10-01T00:00:02Z",
                completed_at="2026-10-01T00:00:03Z",
            )["id"]
        )
        # A later inserted backfill must not replace the newest actual attempt.
        insert_qa_run(
            test_db,
            qa_requirement_id=requirement_id,
            verdict="fail",
            verdict_reason="Older actual failure",
            started_at="2026-10-01T00:00:00Z",
            completed_at="2026-10-01T00:00:01Z",
        )
    _waive(test_db, requirement_id)
    before = test_db.execute("SELECT COUNT(*) FROM qa_runs").fetchone()[0]

    detail = get_plan(test_db, plan_id=plan_id)
    listed = _listed(test_db, plan_id)

    proof = detail["cases"][0]["last_result"]
    assert proof["outcome"] == listed["last_outcome"] == "waived"
    assert proof["requirement_id"] == requirement_id
    assert proof["run_id"] == run_id
    assert detail["union"] == {"satisfied": True, "counts": {"waived": 1}}
    assert listed["last_verdict_reason"] == (
        "Actual newest failure" if after_failure else None
    )
    assert test_db.execute("SELECT COUNT(*) FROM qa_runs").fetchone()[0] == before


def test_waiver_does_not_cross_case_baseline_or_target(test_db):
    item_id, plan_id = _plan(test_db)
    requirement_id = _requirement(
        test_db, item_id, plan_id, host_baseline="fresh-host", target_env="stage"
    )
    _waive(test_db, requirement_id)

    proof = _case_result(test_db, plan_id, CASE_KEY, "fresh-host", None, "stage")
    assert proof["outcome"] == "waived"
    assert proof["requirement_id"] == requirement_id
    for case_key, baseline, environment in [
        (CASE_KEY, "fresh-host", "prod"),
        (CASE_KEY, None, "stage"),
        ("different", "fresh-host", "stage"),
    ]:
        other = _case_result(test_db, plan_id, case_key, baseline, None, environment)
        assert other["outcome"] == "not_run"
        assert other["requirement_id"] is None
    assert get_plan(test_db, plan_id=plan_id)["union"]["satisfied"] is False


@pytest.mark.parametrize(
    "retirement",
    ["superseded_by_requirement_id", "replacement_requirement_id", "retracted_at"],
)
def test_retired_waiver_cannot_mask_current_failure_in_detail_or_list(
    test_db, retirement
):
    item_id, plan_id = _plan(test_db)
    current_id = _requirement(test_db, item_id, plan_id)
    run_id = int(
        insert_qa_run(test_db, qa_requirement_id=current_id, verdict="fail")["id"]
    )
    value = "2026-10-01T00:00:00Z" if retirement == "retracted_at" else current_id
    retired_id = _requirement(
        test_db,
        item_id,
        plan_id,
        created_at="2060-01-01T00:00:00Z",
        **{retirement: value},
    )
    _waive(test_db, retired_id)

    detail = get_plan(test_db, plan_id=plan_id)
    assert detail["cases"][0]["last_result"]["requirement_id"] == current_id
    assert detail["cases"][0]["last_result"]["run_id"] == run_id
    assert detail["union"] == {"satisfied": False, "counts": {"failed": 1}}
    assert _listed(test_db, plan_id)["last_outcome"] == "failed"


def test_current_triage_remains_excluded_even_with_a_visible_waiver(test_db):
    item_id, plan_id = _plan(test_db)
    triage_item, triage_id, _attempt, ref, actor = _seed(test_db)
    test_db.execute(
        "UPDATE qa_requirements SET plan_id=%s,plan_case_key=%s WHERE id=%s",
        (plan_id, CASE_KEY, triage_id),
    )
    test_db.commit()
    with acting_event_identity(session_id="simulation-owner", actor_id=actor):
        _record(test_db, triage_item, [ref])
    _waive(test_db, triage_id)
    current_id = _requirement(test_db, item_id, plan_id)
    insert_qa_run(
        test_db,
        qa_requirement_id=current_id,
        verdict="fail",
        started_at="2026-09-01T00:00:00Z",
        completed_at="2026-09-01T00:00:01Z",
    )

    detail = get_plan(test_db, plan_id=plan_id)
    assert detail["cases"][0]["last_result"]["requirement_id"] == current_id
    assert detail["union"] == {"satisfied": False, "counts": {"failed": 1}}
    assert _listed(test_db, plan_id)["last_outcome"] == "failed"
