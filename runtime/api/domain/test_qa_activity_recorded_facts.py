"""Activity and item-detail reads must surface recorded post-deploy facts.

Executable-only activity hid no-obligation and waiver-backed "not required"
rows, so a release card could not tell those from never-asked. Item detail
keyed only on ``item_id``, so an admitted per-run copy (``item_id`` null,
``deployment_member_item_id`` set) never appeared next to its standing source.
"""

from __future__ import annotations

import json

from runtime.api.fixtures.backlog_inserts import insert_item
from runtime.api.fixtures.backlog_qa_inserts import (
    insert_qa_requirement,
    insert_qa_run,
)
from runtime.api.fixtures.pg_testdb import test_database
from yoke_core.domain.item_detail_qa import qa_rows
from yoke_core.domain.qa_activity_reads import list_activity, read_activity
from yoke_core.domain.qa_run_outcome import qa_run_outcome


def test_activity_includes_recorded_post_deploy_facts() -> None:
    with test_database() as conn:
        insert_item(conn, id=4810, title="No obligation member")
        insert_item(conn, id=4811, title="Waived member")
        none = insert_qa_requirement(
            conn,
            item_id=4810,
            qa_kind="post_deploy_no_obligation",
            qa_phase="post_deploy",
            method_id=None,
            instructions="Nothing about this item is observable once deployed.",
        )
        waived = insert_qa_requirement(
            conn,
            item_id=4811,
            qa_kind="post_deploy_not_required",
            qa_phase="post_deploy",
            method_id=None,
            waived_at="2026-09-20T16:14:21Z",
            waiver_rationale="declining it on cost",
        )
        conn.commit()

        rows = list_activity(conn, project="yoke", item_ids=[4810, 4811])
        by_id = {row["requirement_id"]: row for row in rows}
        assert none["id"] in by_id
        assert waived["id"] in by_id
        assert by_id[int(none["id"])]["qa_kind"] == "post_deploy_no_obligation"
        assert by_id[int(none["id"])]["outcome"] == "no_obligation"
        assert by_id[int(waived["id"])]["qa_kind"] == "post_deploy_not_required"
        assert by_id[int(waived["id"])]["waiver_rationale"] == "declining it on cost"


def test_item_detail_includes_admitted_copy_beside_standing_source() -> None:
    with test_database() as conn:
        insert_item(conn, id=4820, title="Standing source item", status="done")
        source = insert_qa_requirement(
            conn,
            item_id=4820,
            qa_kind="plan_case",
            qa_phase="post_deploy",
            plan_case_key="plan-currency-readable",
            method_id="command",
        )
        copy = insert_qa_requirement(
            conn,
            item_id=None,
            deployment_run_id="run-20260920-005",
            deployment_stage="item-qa",
            deployment_member_item_id=4820,
            qa_kind="plan_case",
            qa_phase="post_deploy",
            plan_case_key=f"admitted-requirement-{int(source['id'])}",
            method_id="command",
        )
        insert_qa_run(
            conn,
            qa_requirement_id=int(copy["id"]),
            performed_by="command",
            verdict="pass",
        )
        conn.commit()

        rows = qa_rows(conn, 4820)
        ids = {int(row["id"]) for row in rows}
        assert int(source["id"]) in ids
        assert int(copy["id"]) in ids
        copy_row = next(row for row in rows if int(row["id"]) == int(copy["id"]))
        assert copy_row["plan_case_key"] == f"admitted-requirement-{int(source['id'])}"
        assert copy_row["deployment_member_item_id"] == 4820


def test_activity_returns_execution_target_json() -> None:
    target = {
        "deployment": {
            "release_lineage": "97dce1f6f88d896ab561c066a50b1978c432f481",
            "run_id": "run-20260921-016",
        },
        "observation": {
            "observed_release_lineage": "97dce1f6f88d896ab561c066a50b1978c432f481",
            "source_stage": "warm-up",
        },
    }
    with test_database() as conn:
        insert_item(conn, id=4830, title="Targeted member")
        requirement = insert_qa_requirement(
            conn,
            item_id=4830,
            qa_kind="plan_case",
            qa_phase="post_deploy",
            method_id="command",
            execution_target_json=json.dumps(target),
        )
        conn.commit()
        rows = list_activity(conn, project="yoke", item_ids=[4830])
        row = next(r for r in rows if r["requirement_id"] == int(requirement["id"]))
        assert row["execution_target_json"] == target


def test_latest_planless_capture_is_visible_in_item_activity_and_summary() -> None:
    from datetime import date

    with test_database() as conn:
        insert_item(conn, id=4840, title="Captured item")
        requirement = insert_qa_requirement(
            conn,
            item_id=4840,
            qa_kind="method_case",
            method_id="browser-inspection",
            created_at="2026-09-20T10:00:00Z",
        )
        insert_qa_run(
            conn,
            qa_requirement_id=requirement["id"],
            verdict="fail",
            created_at="2026-09-20T10:01:00Z",
        )
        current = insert_qa_run(
            conn,
            qa_requirement_id=requirement["id"],
            verdict=None,
            execution_status="captured",
            created_at="2026-09-20T10:02:00Z",
        )
        conn.commit()
        item_row = next(
            row for row in qa_rows(conn, 4840) if row["id"] == requirement["id"]
        )
        activity = read_activity(conn, project="yoke", day=date(2026, 9, 20))
        row = next(
            row
            for row in activity["rows"]
            if row["requirement_id"] == requirement["id"]
        )
        assert row["run_id"] == item_row["run_id"] == current["id"]
        assert row["outcome"] == item_row["outcome"] == "captured"
        assert row["execution_status"] == "captured"
        assert activity["summary"]["counts"] == {"captured": 1}


def test_recorded_verdict_takes_precedence_over_capture_bookkeeping() -> None:
    assert (
        qa_run_outcome({"verdict": "pass", "execution_status": "captured"}) == "passed"
    )
    assert qa_run_outcome({"execution_status": "capture_failed"}) == "capture_failed"
