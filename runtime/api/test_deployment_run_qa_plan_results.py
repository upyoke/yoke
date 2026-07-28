"""Deployment-run filtering for QA plan and activity reads."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import date
from unittest.mock import patch

from runtime.api.fixtures.backlog_inserts import (
    insert_deployment_run,
    insert_item,
)
from runtime.api.fixtures.pg_testdb import test_database
from runtime.api.qa_catalog_test_support import create_release_readiness_plan
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain.handlers import qa_catalog_reads as activity_handlers
from yoke_core.domain.qa_catalog_reads import read_activity
from yoke_core.domain.qa_plan_attachments import (
    materialize_for_deployment_run,
    materialize_for_item,
    set_project_default,
)
from yoke_core.domain.qa_plan_detail import get_plan


def test_plan_and_activity_reads_attribute_named_deployment_run_proof() -> None:
    deployment_run_id = "run-20260728-904"
    with test_database() as conn:
        insert_deployment_run(conn, id=deployment_run_id)
        insert_item(conn, id=42, title="Ship checkout", workflow_id="issue")
        plan = create_release_readiness_plan(conn)
        set_project_default(
            conn,
            plan_id=plan["id"],
            workflow_id="issue",
            transition_id="release",
        )
        item_requirements = materialize_for_item(
            conn,
            item_id=42,
            transition_id="release",
        )
        deployment_requirements = materialize_for_deployment_run(
            conn,
            deployment_run_id=deployment_run_id,
            plan="release-readiness",
            project="yoke",
        )
        conn.execute(
            "INSERT INTO qa_runs("
            "qa_requirement_id,executor_type,qa_kind,verdict,case_outcome,"
            "created_at"
            ") VALUES (%s,'worktree_run','command','pass','passed',"
            "'2026-07-28T12:00:00Z')",
            (deployment_requirements["created_requirement_ids"][0],),
        )
        conn.execute(
            "INSERT INTO qa_runs("
            "qa_requirement_id,executor_type,qa_kind,verdict,case_outcome,"
            "created_at"
            ") VALUES (%s,'worktree_run','command','fail','failed',"
            "'2026-07-28T13:00:00Z')",
            (item_requirements["created_requirement_ids"][0],),
        )
        conn.commit()

        unfiltered = get_plan(conn, plan_id=plan["id"])
        deployment = get_plan(
            conn,
            plan_id=plan["id"],
            deployment_run_id=deployment_run_id,
        )
        activity = read_activity(
            conn,
            project="yoke",
            deployment_run_id=deployment_run_id,
            day=date(2026, 7, 28),
        )

    assert unfiltered["cases"][0]["last_result"]["outcome"] == "failed"
    assert unfiltered["cases"][0]["last_result"]["deployment_run_id"] is None
    assert deployment["deployment_run_id"] == deployment_run_id
    assert deployment["cases"][0]["last_result"]["outcome"] == "passed"
    assert (
        deployment["cases"][0]["last_result"]["deployment_run_id"] == deployment_run_id
    )
    assert {row["deployment_run_id"] for row in activity["rows"]} == {deployment_run_id}
    assert activity["summary"] == {
        "day": "2026-07-28",
        "total": 2,
        "counts": {"passed": 1, "queued": 1},
    }


def test_plan_get_handler_forwards_the_named_deployment_run() -> None:
    @contextmanager
    def connected():
        yield object()

    request = FunctionCallRequest(
        function="qa.plan.get",
        actor=ActorContext(actor_id="op", session_id="s-1"),
        target=TargetRef(kind="global"),
        payload={
            "project": "yoke",
            "plan_id": 17,
            "deployment_run_id": "run-20260728-905",
        },
    )
    with (
        patch("yoke_core.domain.db_helpers.connect", connected),
        patch(
            "yoke_core.domain.qa_plan_detail.get_plan",
            return_value={"project": "yoke"},
        ) as read,
    ):
        outcome = activity_handlers.handle_plan_get(request)

    assert outcome.primary_success
    assert read.call_args.kwargs == {
        "plan_id": 17,
        "deployment_run_id": "run-20260728-905",
    }
