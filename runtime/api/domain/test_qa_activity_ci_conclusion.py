"""QA activity must project a CI run conclusion the reader can open."""

from __future__ import annotations

import json

from runtime.api.fixtures.backlog_inserts import insert_item
from runtime.api.fixtures.backlog_qa_inserts import (
    insert_qa_requirement,
    insert_qa_run,
)
from runtime.api.fixtures.pg_testdb import test_database
from yoke_core.domain.qa_activity_reads import list_activity
from yoke_core.domain.qa_plan_management import create_plan

SHA = "f81d1ad1a61c" + "0" * 28
RUN_URL = "https://github.test/upyoke/yoke/actions/runs/399"


def test_activity_projects_ci_conclusion_when_the_run_has_no_artifacts() -> None:
    with test_database() as conn:
        insert_item(conn, id=4620, title="CI conclusion")
        plan = create_plan(
            conn, project="yoke", slug="ci-conclusion", name="CI conclusion"
        )
        requirement = insert_qa_requirement(
            conn,
            item_id=4620,
            plan_id=int(plan["id"]),
            plan_case_key="backend-suite",
            method_id="command",
        )
        insert_qa_run(
            conn,
            qa_requirement_id=int(requirement["id"]),
            performed_by="ci_run",
            verdict="pass",
            raw_result=json.dumps(
                {
                    "ci_run_id": "399",
                    "ci_conclusion": "success",
                    "run_url": RUN_URL,
                    "exit_code": 0,
                    "verification_tree": {"head_sha": SHA},
                }
            ),
        )
        activity = list_activity(conn, project="yoke")

    row = next(item for item in activity if item["case_key"] == "backend-suite")
    assert row["artifacts"] == []
    assert row["evidence_count"] == 0
    assert row["recorded_head_sha"] == SHA
    assert row["run_url"] == RUN_URL
    assert row["ci_conclusion"] == "success"
    assert row["proof_summary"] == f"verified {SHA[:12]} · GitHub Actions run"
