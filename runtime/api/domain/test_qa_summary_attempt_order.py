"""Summary readers follow actual attempt starts rather than audit recency."""

import pytest

from runtime.api.fixtures.backlog_inserts import insert_item
from runtime.api.fixtures.backlog_qa_inserts import insert_qa_requirement, insert_qa_run
from runtime.api.qa_method_related_plans_test_support import _case
from yoke_core.domain.qa_activity_reads import list_activity
from yoke_core.domain.qa_method_related_plans import read_method_related_plans
from yoke_core.domain.qa_plan_management import create_plan, replace_plan_cases


@pytest.mark.parametrize("reader", ["activity", "method"])
def test_summary_selects_start_instant_before_verdict_and_creation(test_db, reader):
    insert_item(test_db, id=7143, title="Current summary proof")
    plan = create_plan(
        test_db, project="yoke", slug="current-summary", name="Current summary"
    )
    replace_plan_cases(
        test_db, plan_id=plan["id"], cases=[_case("command", 1, "command")]
    )
    requirement = insert_qa_requirement(
        test_db,
        item_id=7143,
        plan_id=plan["id"],
        plan_case_key="command",
        method_id="command",
    )
    # The pass was stored later, but started an hour before the failure.
    failing = insert_qa_run(
        test_db,
        qa_requirement_id=requirement["id"],
        performed_by="test_runner",
        started_at="2026-10-01T08:00:00-04:00",
        created_at="2026-10-01T12:00:00Z",
        verdict="fail",
        case_outcome="failed",
    )
    insert_qa_run(
        test_db,
        qa_requirement_id=requirement["id"],
        performed_by="test_runner",
        started_at="2026-10-01T13:00:00+02:00",
        created_at="2026-10-01T13:00:00Z",
        verdict="pass",
        case_outcome="passed",
    )
    if reader == "activity":
        row = list_activity(test_db, project="yoke", item_ids=[7143])[0]
        assert row["run_id"] == failing["id"]
        assert row["outcome"] == "failed"
    else:
        plans = read_method_related_plans(test_db, method_id="command", project_id=1)
        summary = next(p for p in plans if p["id"] == plan["id"])["outcome_summary"]
        assert summary["state"] == "failed"
        assert summary["counts"] == {"failed": 1}
