"""Activity and item-detail reads must surface recorded post-deploy facts.

Executable-only activity hid no-obligation and waiver-backed "not required"
rows, so a release card could not tell those from never-asked. Item detail
keyed only on ``item_id``, so an admitted per-run copy (``item_id`` null,
``deployment_member_item_id`` set) never appeared next to its standing source.
"""

from __future__ import annotations

from runtime.api.fixtures.backlog_inserts import insert_item
from runtime.api.fixtures.backlog_qa_inserts import (
    insert_qa_requirement,
    insert_qa_run,
)
from runtime.api.fixtures.pg_testdb import test_database
from yoke_core.domain.item_detail_qa import qa_rows
from yoke_core.domain.qa_activity_reads import list_activity


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
