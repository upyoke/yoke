"""A case is visible because it executes, not because it has a plan.

The activity read used to require a plan row, and took its project scope
from that plan. Every executable case attached without one — an item's own
ad hoc verification, a case authored straight against a deployment run —
recorded passing runs and screenshots that no surface could read back, so
an item's evidence looked absent while it sat in storage.

What must stay out is the other planless shape: the method-less bookkeeping
row, which never executes and has no verdict or evidence to show.
"""

from __future__ import annotations

from datetime import date

from runtime.api.fixtures.backlog_inserts import (
    insert_deployment_run,
    insert_item,
)
from runtime.api.fixtures.backlog_qa_inserts import (
    insert_qa_requirement,
    insert_qa_run,
)
from runtime.api.fixtures.pg_testdb import test_database
from yoke_core.domain.qa_activity_reads import list_activity, read_activity


def _requirement_ids(rows) -> set[int]:
    return {int(row["requirement_id"]) for row in rows}


def test_item_case_without_a_plan_is_read_back_with_its_evidence() -> None:
    with test_database() as conn:
        insert_item(conn, id=5210, title="Ad hoc verified item")
        requirement = insert_qa_requirement(
            conn,
            item_id=5210,
            qa_kind="method_case",
            method_id="browser-inspection",
            method_name="Browser inspection",
        )
        run = insert_qa_run(
            conn,
            qa_requirement_id=int(requirement["id"]),
            performed_by="host_control",
            verdict="pass",
        )
        conn.execute(
            "INSERT INTO qa_artifacts(qa_run_id, artifact_type, created_at) "
            "VALUES (%s, 'browser_screenshot', %s)",
            (int(run["id"]), "2026-09-16T00:00:00Z"),
        )
        conn.commit()

        rows = list_activity(conn, project="yoke", item_ids=[5210])
        row = next(r for r in rows if r["requirement_id"] == int(requirement["id"]))

        assert row["evidence_count"] == 1
        assert row["outcome"] == "passed"
        # No plan is a real attachment shape, so the plan fields read as
        # absent rather than as the string "None".
        assert row["plan_id"] is None
        assert row["plan"] is None
        assert row["case_key"] is None
        assert row["project"] == "yoke"


def test_method_less_bookkeeping_row_stays_out_of_activity() -> None:
    with test_database() as conn:
        insert_item(conn, id=5220, title="Item with an AC marker")
        marker = insert_qa_requirement(
            conn,
            item_id=5220,
            qa_kind="ac_verification",
            requirement_source="ac_derived",
        )

        rows = list_activity(conn, project="yoke", item_ids=[5220])

        assert int(marker["id"]) not in _requirement_ids(rows)


def test_run_attached_case_without_a_plan_is_read_back() -> None:
    with test_database() as conn:
        insert_deployment_run(conn, id="run-20260916-901", status="executing")
        requirement = insert_qa_requirement(
            conn,
            item_id=None,
            deployment_run_id="run-20260916-901",
            qa_kind="method_case",
            method_id="browser-inspection",
            method_name="Browser inspection",
        )
        insert_qa_run(
            conn,
            qa_requirement_id=int(requirement["id"]),
            performed_by="host_control",
            verdict="pass",
        )

        rows = list_activity(conn, project="yoke", deployment_run_id="run-20260916-901")

        assert _requirement_ids(rows) == {int(requirement["id"])}
        # The run carries the project scope its plan used to supply.
        assert rows[0]["project"] == "yoke"
        assert rows[0]["deployment_run_id"] == "run-20260916-901"


def test_planless_cases_stay_inside_their_own_project() -> None:
    with test_database() as conn:
        insert_item(conn, id=5230, title="Ours", project="yoke")
        insert_item(conn, id=5231, title="Theirs", project="other-project")
        ours = insert_qa_requirement(
            conn, item_id=5230, qa_kind="method_case", method_id="command-ci"
        )
        theirs = insert_qa_requirement(
            conn, item_id=5231, qa_kind="method_case", method_id="command-ci"
        )

        rows = list_activity(conn, project="yoke")

        assert int(ours["id"]) in _requirement_ids(rows)
        assert int(theirs["id"]) not in _requirement_ids(rows)


def test_day_summary_counts_the_same_cases_the_rows_show() -> None:
    """A summary narrower than its own rows reports a day that never was."""
    with test_database() as conn:
        insert_item(conn, id=5240, title="Summarized item")
        requirement = insert_qa_requirement(
            conn,
            item_id=5240,
            qa_kind="method_case",
            method_id="command-ci",
            created_at="2026-09-16T10:00:00Z",
        )
        insert_qa_run(
            conn,
            qa_requirement_id=int(requirement["id"]),
            performed_by="host_control",
            verdict="pass",
            created_at="2026-09-16T10:05:00Z",
            completed_at="2026-09-16T10:05:00Z",
        )

        result = read_activity(
            conn,
            project="yoke",
            item_ids=[5240],
            day=date(2026, 9, 16),
        )

        assert result["summary"]["total"] == 1
        assert result["summary"]["counts"] == {"passed": 1}


def test_a_planless_case_reports_its_current_attempt_not_an_older_one() -> None:
    """A re-run supersedes; the row a surface shows is the latest attempt."""
    with test_database() as conn:
        insert_item(conn, id=5250, title="Re-run item")
        requirement = insert_qa_requirement(
            conn,
            item_id=5250,
            qa_kind="method_case",
            method_id="browser-inspection",
        )
        insert_qa_run(
            conn,
            qa_requirement_id=int(requirement["id"]),
            performed_by="host_control",
            verdict="fail",
            created_at="2026-09-16T09:00:00Z",
        )
        current = insert_qa_run(
            conn,
            qa_requirement_id=int(requirement["id"]),
            performed_by="host_control",
            verdict="pass",
            created_at="2026-09-16T11:00:00Z",
        )

        rows = list_activity(conn, project="yoke", item_ids=[5250])
        row = next(r for r in rows if r["requirement_id"] == int(requirement["id"]))

        assert row["run_id"] == int(current["id"])
        assert row["outcome"] == "passed"
