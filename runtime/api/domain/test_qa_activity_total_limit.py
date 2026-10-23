"""An item activity read without run groups returns at most ``limit`` rows."""

from __future__ import annotations

from collections import Counter
from contextlib import contextmanager
from unittest.mock import patch

from runtime.api.fixtures.backlog_inserts import insert_item
from runtime.api.fixtures.backlog_qa_inserts import (
    insert_qa_requirement,
    insert_qa_run,
)
from runtime.api.fixtures.pg_testdb import test_database
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain.handlers import qa_catalog_reads as activity_handlers
from yoke_core.domain.qa_activity_reads import read_activity
from yoke_core.domain.qa_plan_management import create_plan

RUNS = [f"run-2026060{index}-001" for index in range(1, 6)]


def _seed_item_in_five_runs(conn, item_id: int) -> None:
    """Two checks per run, so every run group can overrun a cap of one."""
    insert_item(conn, id=item_id, title="Carried by five releases")
    plan = create_plan(conn, project="yoke", slug="five-runs", name="Five runs")
    for index, run in enumerate(RUNS):
        for check in range(2):
            requirement = insert_qa_requirement(
                conn,
                item_id=None,
                deployment_run_id=run,
                deployment_stage="release",
                deployment_member_item_id=item_id,
                plan_id=int(plan["id"]),
                plan_case_key=f"case-{index}-{check}",
                method_id="terminal-inspection",
                created_at=f"2026-06-0{index + 1}T0{check}:00:00Z",
            )
            insert_qa_run(
                conn,
                qa_requirement_id=int(requirement["id"]),
                performed_by="host_control",
                verdict="pass",
                created_at=f"2026-06-0{index + 1}T0{check}:00:00Z",
            )


def _activity_list(conn, payload: dict) -> dict:
    @contextmanager
    def connected():
        yield conn

    request = FunctionCallRequest(
        function="qa.activity.list",
        actor=ActorContext(actor_id="op", session_id="s-1"),
        target=TargetRef(kind="global"),
        payload=payload,
    )
    with patch("yoke_core.domain.db_helpers.connect", connected):
        outcome = activity_handlers.handle_activity_list(request)
    assert outcome.primary_success, outcome.error
    activity_handlers.ActivityListResponse.model_validate(outcome.result_payload)
    return outcome.result_payload


def test_item_read_without_run_groups_returns_exactly_the_limit() -> None:
    """Per-run bounding there grew with the item's lifetime, not the limit."""
    with test_database() as conn:
        _seed_item_in_five_runs(conn, 4850)

        result = _activity_list(
            conn, {"project": "yoke", "item_ids": [4850], "limit": 3}
        )

        rows = result["rows"]
        assert len(rows) == 3, rows
        # Newest first: the latest run's two checks, then the next run's.
        assert [row["deployment_run_id"] for row in rows] == [
            RUNS[4],
            RUNS[4],
            RUNS[3],
        ]
        assert result["item_selection"] == {
            "limit": 3,
            "total": 10,
            "truncated": True,
        }


def test_item_read_under_the_limit_says_nothing_was_cut() -> None:
    with test_database() as conn:
        _seed_item_in_five_runs(conn, 4851)

        result = read_activity(conn, project="yoke", item_ids=[4851], limit=50)

        assert len(result["rows"]) == 10
        assert result["item_selection"] == {
            "limit": 50,
            "total": 10,
            "truncated": False,
        }


def test_card_reads_naming_run_groups_keep_the_per_run_bound() -> None:
    """A deployment card sizes its read by the runs it draws."""
    with test_database() as conn:
        _seed_item_in_five_runs(conn, 4852)

        result = _activity_list(
            conn,
            {
                "project": "yoke",
                "item_ids": [4852],
                "deployment_run_ids": RUNS,
                "limit": 1,
            },
        )

        per_run = Counter(row["deployment_run_id"] for row in result["rows"])
        assert per_run == {run: 1 for run in RUNS}
        assert result["item_selection"] == {
            "per_group_limit": 1,
            "truncated_groups": [
                {"item_id": 4852, "deployment_run_id": run} for run in RUNS
            ],
        }
