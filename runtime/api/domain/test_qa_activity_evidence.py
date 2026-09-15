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

from collections import Counter
import json

from runtime.api.fixtures.backlog_inserts import insert_item
from runtime.api.fixtures.backlog_qa_inserts import (
    insert_qa_requirement,
    insert_qa_run,
)
from runtime.api.fixtures.pg_testdb import test_database
from yoke_core.domain.qa_activity_reads import list_activity, read_activity
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


def test_a_busy_item_cannot_hide_another_carried_item() -> None:
    """One subject's volume must never cost another subject its evidence.

    A single recency page over several subjects is a defect rather than a
    page: the busiest item fills the cap and every other requested item
    reads back as having no evidence and no waiting review, which is
    exactly the state a card would then report to an approver.
    """
    with test_database() as conn:
        insert_item(conn, id=4810, title="Busy item")
        insert_item(conn, id=4811, title="Quiet item")
        plan = create_plan(
            conn, project="yoke", slug="busy-subject", name="Busy subject"
        )
        quiet = insert_qa_requirement(
            conn,
            item_id=4811,
            plan_id=int(plan["id"]),
            plan_case_key="quiet-case",
            method_id="terminal-inspection",
            created_at="2026-01-01T00:00:00Z",
        )
        insert_qa_run(
            conn,
            qa_requirement_id=int(quiet["id"]),
            performed_by="host_control",
            verdict="pass",
            created_at="2026-01-01T00:00:00Z",
        )
        # Every one of these is newer than the quiet item's only check, so
        # under a single shared cap they would take the whole page.
        for index in range(12):
            busy = insert_qa_requirement(
                conn,
                item_id=4810,
                plan_id=int(plan["id"]),
                plan_case_key=f"busy-case-{index}",
                method_id="terminal-inspection",
                created_at=f"2026-06-{index + 1:02d}T00:00:00Z",
            )
            insert_qa_run(
                conn,
                qa_requirement_id=int(busy["id"]),
                performed_by="host_control",
                verdict="pass",
                created_at=f"2026-06-{index + 1:02d}T00:00:00Z",
            )

        result = read_activity(conn, project="yoke", item_ids=[4810, 4811], limit=5)

        subjects = {row["item_id"] for row in result["rows"]}
        assert subjects == {4810, 4811}, result["rows"]
        per_item = Counter(row["item_id"] for row in result["rows"])
        assert per_item[4810] == 5
        assert per_item[4811] == 1
        # The busy item was cut short; the quiet one was not, and saying so
        # is the difference between a bounded read and a silent omission.
        # Truncation names the group, because that is what was bounded.
        assert result["item_selection"] == {
            "per_group_limit": 5,
            "truncated_groups": [{"item_id": 4810, "deployment_run_id": None}],
        }


def test_a_requirement_with_no_run_stays_visible() -> None:
    """A check nobody has run yet is what a pending review is attached to."""
    with test_database() as conn:
        insert_item(conn, id=4820, title="Awaiting review")
        plan = create_plan(conn, project="yoke", slug="no-run-yet", name="No run yet")
        requirement = insert_qa_requirement(
            conn,
            item_id=4820,
            plan_id=int(plan["id"]),
            plan_case_key="never-run",
            method_id="terminal-inspection",
        )

        rows = list_activity(conn, project="yoke", item_ids=[4820])

        assert [row["requirement_id"] for row in rows] == [int(requirement["id"])]
        assert rows[0]["run_id"] is None
        assert rows[0]["artifacts"] == []


def test_one_release_worth_of_checks_cannot_hide_another_release_s() -> None:
    """Bounding an item as a whole would cut the rows a card needs.

    A card draws one run. If the read bounds the item across every run it
    ever took part in, the busiest release's checks arrive newest and the
    rows belonging to the run actually being drawn never reach the caller
    that would have filtered to them.
    """
    with test_database() as conn:
        insert_item(conn, id=4830, title="Carried by several releases")
        plan = create_plan(
            conn, project="yoke", slug="several-releases", name="Several releases"
        )
        older = insert_qa_requirement(
            conn,
            item_id=None,
            deployment_run_id="run-20260101-001",
            deployment_stage="release",
            deployment_member_item_id=4830,
            plan_id=int(plan["id"]),
            plan_case_key="older-release",
            method_id="terminal-inspection",
            created_at="2026-01-01T00:00:00Z",
        )
        insert_qa_run(
            conn,
            qa_requirement_id=int(older["id"]),
            performed_by="host_control",
            verdict="pass",
            created_at="2026-01-01T00:00:00Z",
        )
        for index in range(8):
            newer = insert_qa_requirement(
                conn,
                item_id=None,
                deployment_run_id="run-20260601-009",
                deployment_stage="release",
                deployment_member_item_id=4830,
                plan_id=int(plan["id"]),
                plan_case_key=f"newer-release-{index}",
                method_id="terminal-inspection",
                created_at=f"2026-06-{index + 1:02d}T00:00:00Z",
            )
            insert_qa_run(
                conn,
                qa_requirement_id=int(newer["id"]),
                performed_by="host_control",
                verdict="pass",
                created_at=f"2026-06-{index + 1:02d}T00:00:00Z",
            )

        result = read_activity(conn, project="yoke", item_ids=[4830], limit=3)

        runs = Counter(row["deployment_run_id"] for row in result["rows"])
        assert runs["run-20260101-001"] == 1, result["rows"]
        assert runs["run-20260601-009"] == 3
        # Only the release that overran is named, not the item at large.
        assert result["item_selection"]["truncated_groups"] == [
            {"item_id": 4830, "deployment_run_id": "run-20260601-009"},
        ]


def test_only_the_run_groups_a_caller_draws_come_back() -> None:
    """An answer sized by a lifetime of releases is not a bounded answer.

    Every release an item ever took part in is a run group, and a caller
    drawing one card needs exactly two of them: that release, and the item's
    own run-less checks.
    """
    with test_database() as conn:
        insert_item(conn, id=4840, title="Long-lived item")
        plan = create_plan(
            conn, project="yoke", slug="many-releases", name="Many releases"
        )
        own = insert_qa_requirement(
            conn,
            item_id=4840,
            plan_id=int(plan["id"]),
            plan_case_key="item-own",
            method_id="terminal-inspection",
        )
        drawn = insert_qa_requirement(
            conn,
            item_id=None,
            deployment_run_id="run-20260601-009",
            deployment_stage="release",
            deployment_member_item_id=4840,
            plan_id=int(plan["id"]),
            plan_case_key="drawn-release",
            method_id="terminal-inspection",
        )
        for index in range(5):
            insert_qa_requirement(
                conn,
                item_id=None,
                deployment_run_id=f"run-20250101-{index:03d}",
                deployment_stage="release",
                deployment_member_item_id=4840,
                plan_id=int(plan["id"]),
                plan_case_key=f"old-release-{index}",
                method_id="terminal-inspection",
            )

        rows = list_activity(
            conn,
            project="yoke",
            item_ids=[4840],
            deployment_run_ids=["run-20260601-009"],
        )

        assert sorted(row["requirement_id"] for row in rows) == sorted(
            [int(own["id"]), int(drawn["id"])]
        )
