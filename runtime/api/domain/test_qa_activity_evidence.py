"""QA activity rows must resolve evidence through a review's capture run.

The activity table (and its per-run detail route) once counted and linked
only a requirement's own bare latest run, so a review verdict pointing at an
earlier capture run reported no screenshots despite that capture owning real
artifacts — the same broken assumption fixed on the item and plan detail
readers.
"""

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


def test_activity_resolves_agent_review_evidence_to_capture_run() -> None:
    with test_database() as conn:
        insert_item(conn, id=4610, title="Activity evidence")
        plan = create_plan(
            conn, project="yoke", slug="activity-evidence", name="Activity evidence"
        )
        requirement = insert_qa_requirement(
            conn,
            item_id=4610,
            plan_id=int(plan["id"]),
            plan_case_key="review-frame",
            method_id="terminal-inspection",
        )
        capture_run = insert_qa_run(
            conn,
            qa_requirement_id=int(requirement["id"]),
            performed_by="host_control",
            verdict="pass",
        )
        conn.execute(
            "INSERT INTO qa_artifacts(qa_run_id, artifact_type, created_at) "
            "VALUES (%s, 'terminal_screenshot', %s)",
            (int(capture_run["id"]), "2026-07-29T00:00:00Z"),
        )
        conn.commit()
        insert_qa_run(
            conn,
            qa_requirement_id=int(requirement["id"]),
            performed_by="agent",
            verdict="pass",
            raw_result=json.dumps({"capture_run_id": int(capture_run["id"])}),
        )

        rows = list_activity(conn, project="yoke")
        row = next(r for r in rows if r["requirement_id"] == int(requirement["id"]))

        assert row["evidence_count"] == 1
        assert [artifact["artifact_type"] for artifact in row["artifacts"]] == (
            ["terminal_screenshot"]
        )
