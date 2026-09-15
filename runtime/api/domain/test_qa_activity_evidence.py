"""QA activity rows must resolve evidence through a review's capture run.

The activity table (and its per-run detail route) once counted and linked
only a requirement's own bare latest run, so a review verdict pointing at an
earlier capture run reported no screenshots despite that capture owning real
artifacts — the same broken assumption fixed on the item and plan detail
readers.

The same read also answers the item direction, because a surface showing a
known set of subjects — the items a release carries — must read their QA
rather than whatever QA happens to be most recent.
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


def test_activity_reads_one_item_however_its_requirement_is_attached() -> None:
    """An item's evidence is both shapes: its own, and its member checks.

    An item-attached requirement records no deployment run at all, so a
    caller that could only filter by run saw nothing for it.
    """
    with test_database() as conn:
        insert_item(conn, id=4710, title="Carried item")
        insert_item(conn, id=4711, title="Another item")
        plan = create_plan(
            conn, project="yoke", slug="carried-evidence", name="Carried evidence"
        )
        own = insert_qa_requirement(
            conn,
            item_id=4710,
            plan_id=int(plan["id"]),
            plan_case_key="item-own",
            method_id="terminal-inspection",
        )
        member = insert_qa_requirement(
            conn,
            item_id=None,
            deployment_run_id="run-20260910-009",
            deployment_member_item_id=4710,
            deployment_stage="release",
            plan_id=int(plan["id"]),
            plan_case_key="member-check",
            method_id="terminal-inspection",
        )
        other = insert_qa_requirement(
            conn,
            item_id=4711,
            plan_id=int(plan["id"]),
            plan_case_key="other-item",
            method_id="terminal-inspection",
        )
        for requirement in (own, member, other):
            insert_qa_run(
                conn,
                qa_requirement_id=int(requirement["id"]),
                performed_by="host_control",
                verdict="pass",
            )

        rows = list_activity(conn, project="yoke", item_ids=[4710])

        assert sorted(row["requirement_id"] for row in rows) == sorted(
            [int(own["id"]), int(member["id"])]
        )
        assert int(other["id"]) not in {row["requirement_id"] for row in rows}
        by_id = {row["requirement_id"]: row for row in rows}
        assert by_id[int(own["id"])]["item_id"] == 4710
        assert by_id[int(own["id"])]["deployment_run_id"] is None
        assert by_id[int(member["id"])]["deployment_member_item_id"] == 4710
        assert by_id[int(member["id"])]["deployment_stage"] == "release"


def test_activity_asked_for_no_items_returns_no_rows() -> None:
    """An empty selection means no subjects, never every subject."""
    with test_database() as conn:
        insert_item(conn, id=4720, title="Carried item")
        plan = create_plan(
            conn, project="yoke", slug="empty-selection", name="Empty selection"
        )
        requirement = insert_qa_requirement(
            conn,
            item_id=4720,
            plan_id=int(plan["id"]),
            plan_case_key="item-own",
            method_id="terminal-inspection",
        )
        insert_qa_run(
            conn,
            qa_requirement_id=int(requirement["id"]),
            performed_by="host_control",
            verdict="pass",
        )

        assert list_activity(conn, project="yoke", item_ids=[]) == []
        assert list_activity(conn, project="yoke") != []
