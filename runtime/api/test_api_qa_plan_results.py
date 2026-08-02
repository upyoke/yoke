"""QA plan materialization, activity, and proof-union contract tests."""

from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import date
from unittest.mock import patch

from runtime.api.fixtures.backlog_inserts import insert_item
from runtime.api.fixtures.pg_testdb import test_database
from runtime.api.qa_catalog_test_support import (
    CATALOG_CASES,
    create_release_readiness_plan,
)
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain.handlers import qa_catalog_reads as activity_handlers
from yoke_core.domain.qa_catalog_reads import list_activity, read_activity
from yoke_core.domain.qa_plan_attachments import (
    materialize_for_item,
    set_project_default,
)
from yoke_core.domain.qa_plan_detail import get_plan
from yoke_core.domain.qa_plan_rematerialize import rematerialize_for_item
from yoke_core.domain.qa_plan_management import (
    create_plan,
    replace_plan_cases,
)


def test_materialization_is_idempotent_and_preserves_case_snapshot() -> None:
    with test_database() as conn:
        item = insert_item(
            conn,
            id=42,
            title="Ship checkout",
            workflow_id="issue",
            status="implemented",
        )
        plan = create_release_readiness_plan(conn)
        set_project_default(
            conn,
            plan_id=plan["id"],
            workflow_id=str(item["workflow_id"]),
            transition_id="release",
        )
        first = materialize_for_item(
            conn,
            item_id=42,
            transition_id="release",
        )
        replace_plan_cases(
            conn,
            plan_id=plan["id"],
            cases=[
                {
                    **CATALOG_CASES[0],
                    "instructions": "A later edit for future items.",
                },
                CATALOG_CASES[1],
            ],
        )
        second = materialize_for_item(
            conn,
            item_id=42,
            transition_id="release",
        )
        snapshot = conn.execute(
            "SELECT method_id, qa_kind, instructions, success_policy, "
            "workflow_transition_id FROM qa_requirements "
            "WHERE item_id=%s ORDER BY id",
            (42,),
        ).fetchall()

    assert len(first["created_requirement_ids"]) == 2
    assert second["created_requirement_ids"] == []
    assert second["existing_requirement_ids"] == first["created_requirement_ids"]
    assert snapshot[0]["method_id"] == "command"
    assert snapshot[0]["qa_kind"] == "plan_case"
    assert snapshot[0]["instructions"] == CATALOG_CASES[0]["instructions"]
    assert json.loads(snapshot[0]["success_policy"]) == {
        "id": "all-pass",
        "params": {},
    }
    assert snapshot[1]["qa_kind"] == "plan_case"
    assert snapshot[1]["workflow_transition_id"] == "release"


def test_rematerialization_refreshes_snapshot_and_retains_run_history() -> None:
    with test_database() as conn:
        item = insert_item(conn, id=42, title="Ship checkout", workflow_id="issue")
        plan = create_release_readiness_plan(conn)
        set_project_default(
            conn,
            plan_id=plan["id"],
            workflow_id=str(item["workflow_id"]),
            transition_id="release",
        )
        initial = materialize_for_item(conn, item_id=42, transition_id="release")
        original_id = initial["created_requirement_ids"][0]
        conn.execute(
            "INSERT INTO qa_runs(qa_requirement_id, executor_type, qa_kind, "
            "verdict, case_outcome, raw_result, created_at) VALUES "
            "(%s, 'worktree_run', 'command', 'fail', 'failed', %s, %s)",
            (
                original_id,
                json.dumps({"output_tail": "failed assertion"}),
                "2026-07-26T12:00:00Z",
            ),
        )
        conn.commit()
        replace_plan_cases(
            conn,
            plan_id=plan["id"],
            cases=[
                {**CATALOG_CASES[0], "instructions": "Run the corrected suite."},
                CATALOG_CASES[1],
            ],
        )
        replacement = rematerialize_for_item(
            conn,
            item_id=42,
            transition_id="release",
        )
        snapshots = conn.execute(
            "SELECT id, waived_at, waiver_rationale, waiver_source, instructions "
            "FROM qa_requirements WHERE item_id=%s ORDER BY id",
            (42,),
        ).fetchall()
        retained_runs = conn.execute(
            "SELECT count(*) AS count FROM qa_runs WHERE qa_requirement_id=%s",
            (original_id,),
        ).fetchone()

    assert replacement["created_requirement_ids"] == []
    assert (
        replacement["refreshed_requirement_ids"] == initial["created_requirement_ids"]
    )
    assert replacement["waived_requirement_ids"] == []
    assert len(snapshots) == 2
    assert all(row["waived_at"] is None for row in snapshots)
    assert snapshots[0]["instructions"] == "Run the corrected suite."
    assert retained_runs["count"] == 1


def test_activity_folds_requirement_run_and_artifacts_into_case_outcome() -> None:
    with test_database() as conn:
        insert_item(conn, id=42, title="Ship checkout", workflow_id="issue")
        plan = create_release_readiness_plan(conn)
        set_project_default(
            conn,
            plan_id=plan["id"],
            workflow_id="issue",
            transition_id="release",
        )
        materialized = materialize_for_item(
            conn,
            item_id=42,
            transition_id="release",
        )
        requirement_id = materialized["created_requirement_ids"][0]
        run = conn.execute(
            "INSERT INTO qa_runs("
            "qa_requirement_id, executor_type, qa_kind, verdict, "
            "case_outcome, raw_result, created_at"
            ") VALUES (%s, 'worktree_run', 'command', 'pass', "
            "'passed', %s, '2026-07-26T12:00:00Z') RETURNING id",
            (
                requirement_id,
                json.dumps({"exit_code": 0, "output_tail": "all passed"}),
            ),
        ).fetchone()
        conn.execute(
            "INSERT INTO qa_artifacts("
            "qa_run_id, artifact_type, artifact_handle, created_at"
            ") VALUES (%s, 'command_output', %s, '2026-07-26T12:00:00Z')",
            (run["id"], '{"kind":"local","path":"output.txt"}'),
        )
        conn.commit()
        activity = list_activity(conn, project="yoke")
        detail = get_plan(conn, plan_id=plan["id"])

    passed = next(row for row in activity if row["case_key"] == "backend-suite")
    assert passed["outcome"] == "passed"
    assert passed["evidence_count"] == 1
    assert passed["method_name"] == "Command"
    assert passed["proof_summary"] == "exit 0 · output tail"
    assert detail["cases"][0]["last_result"]["output_tail"] == "all passed"
    assert detail["union"] == {
        "satisfied": False,
        "counts": {"passed": 1, "queued": 1},
    }


def test_activity_summary_counts_the_full_day_before_limiting_recent_rows() -> None:
    activity_day = date(2026, 7, 26)
    with test_database() as conn:
        insert_item(conn, id=42, title="Ship checkout", workflow_id="issue")
        plan = create_plan(
            conn,
            project="yoke",
            slug="daily-activity",
            name="Daily activity",
        )
        replace_plan_cases(
            conn,
            plan_id=plan["id"],
            cases=[
                {
                    **CATALOG_CASES[0],
                    "case_key": f"case-{position}",
                    "position": position,
                }
                for position in range(1, 5)
            ],
        )
        set_project_default(
            conn,
            plan_id=plan["id"],
            workflow_id="issue",
            transition_id="release",
        )
        materialized = materialize_for_item(
            conn,
            item_id=42,
            transition_id="release",
        )
        run_states = [
            ("pass", None, "2026-07-26T12:00:00Z"),
            ("inconclusive", None, "2026-07-26T11:00:00Z"),
            (None, "running", "2026-07-26T10:00:00Z"),
            ("pass", None, "2026-07-25T23:00:00Z"),
        ]
        for requirement_id, (verdict, case_outcome, happened_at) in zip(
            materialized["created_requirement_ids"],
            run_states,
        ):
            conn.execute(
                "INSERT INTO qa_runs("
                "qa_requirement_id, executor_type, qa_kind, verdict, "
                "case_outcome, created_at"
                ") VALUES (%s, 'worktree_run', 'command', %s, %s, %s)",
                (requirement_id, verdict, case_outcome, happened_at),
            )
        conn.commit()

        activity = read_activity(
            conn,
            project="yoke",
            limit=1,
            day=activity_day,
        )

    assert len(activity["rows"]) == 1
    assert activity["summary"] == {
        "day": "2026-07-26",
        "total": 3,
        "counts": {
            "needs_review": 1,
            "passed": 1,
            "running": 1,
        },
    }


def test_activity_handler_preserves_the_additive_summary_contract() -> None:
    result = {
        "rows": [{"requirement_id": 9}],
        "summary": {
            "day": "2026-07-26",
            "total": 10,
            "counts": {"passed": 8, "needs_review": 1, "running": 1},
        },
    }

    @contextmanager
    def connected():
        yield object()

    request = FunctionCallRequest(
        function="qa.activity.list",
        actor=ActorContext(actor_id="op", session_id="s-1"),
        target=TargetRef(kind="global"),
        payload={"project": "yoke", "limit": 6},
    )
    with (
        patch(
            "yoke_core.domain.db_helpers.connect",
            connected,
        ),
        patch(
            "yoke_core.domain.qa_catalog_reads.read_activity",
            return_value=result,
        ) as read,
    ):
        outcome = activity_handlers.handle_activity_list(request)

    assert outcome.primary_success
    assert outcome.result_payload == result
    validated = activity_handlers.ActivityListResponse.model_validate(
        outcome.result_payload,
    )
    assert validated.summary.total == 10
    assert read.call_args.kwargs == {
        "project": "yoke",
        "deployment_run_id": None,
        "limit": 6,
    }
