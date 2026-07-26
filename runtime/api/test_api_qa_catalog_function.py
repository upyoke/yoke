"""QA catalog, plan management, and materialization contract tests."""

from __future__ import annotations

import json

from runtime.api.fixtures.backlog_inserts import insert_item
from runtime.api.fixtures.pg_testdb import test_database
from yoke_core.domain.qa_catalog_reads import (
    get_method,
    list_activity,
    list_methods,
    list_plans,
)
from yoke_core.domain.qa_plan_attachments import (
    materialize_for_item,
    set_project_default,
)
from yoke_core.domain.qa_plan_detail import get_plan
from yoke_core.domain.qa_plan_management import (
    create_plan,
    replace_plan_cases,
)


CASES = [
    {
        "case_key": "backend-suite",
        "position": 1,
        "method_id": "command",
        "instructions": "Run the registered backend suite.",
        "expected_outcome": "The suite exits successfully.",
        "method_config": {"command": "python3 -m pytest runtime/api"},
    },
    {
        "case_key": "checkout-flow",
        "position": 2,
        "method_id": "browser-check",
        "instructions": "Open checkout and submit the declared fixture.",
        "expected_outcome": "The confirmation route and summary are visible.",
        "method_config": {
            "base_url": "http://localhost:9999",
            "steps": [{"action": "navigate", "route": "/checkout"}],
        },
    },
]


def _plan(conn) -> dict:
    plan = create_plan(
        conn,
        project="yoke",
        slug="release-readiness",
        name="Release readiness",
    )
    replace_plan_cases(conn, plan_id=plan["id"], cases=CASES)
    return plan


def test_builtin_methods_seed_with_real_contracts() -> None:
    with test_database() as conn:
        rows = list_methods(conn, project="yoke")
        command = get_method(conn, method_id="command", project="yoke")

    assert [row["id"] for row in rows] == [
        "command",
        "browser-check",
        "browser-inspection",
        "machine-state-check",
        "terminal-check",
        "terminal-inspection",
    ]
    assert command["executor_id"] == "worktree_run"
    assert command["required_capability_kind"] is None
    assert command["verdict_path"] == "automatic"
    assert command["capability_state"] == "available"


def test_plan_cases_and_attachment_reads_are_project_scoped() -> None:
    with test_database() as conn:
        plan = _plan(conn)
        attached = set_project_default(
            conn,
            plan_id=plan["id"],
            workflow_id="issue",
            transition_id="release",
        )
        rows = list_plans(conn, project="yoke")
        detail = get_plan(conn, plan_id=plan["id"])
        methods = list_methods(conn, project="yoke")

    assert attached["transition_id"] == "release"
    assert len(rows) == 1
    assert rows[0]["case_count"] == 2
    assert rows[0]["materialized_requirement_count"] == 2
    assert rows[0]["attachments"] == [{
        "kind": "project_default",
        "project": "yoke",
        "workflow_id": "issue",
        "transition_id": "release",
        "item_id": None,
    }]
    assert [case["case_key"] for case in detail["cases"]] == [
        "backend-suite",
        "checkout-flow",
    ]
    command = next(row for row in methods if row["id"] == "command")
    assert command["used_by_plan_count"] == 1


def test_multiple_project_default_plans_share_one_transition() -> None:
    with test_database() as conn:
        item = insert_item(
            conn,
            id=42,
            title="Ship checkout",
            workflow_id="issue",
            status="implemented",
        )
        release = _plan(conn)
        lint = create_plan(
            conn,
            project="yoke",
            slug="lint-command",
            name="Lint command",
        )
        replace_plan_cases(
            conn,
            plan_id=lint["id"],
            cases=[{
                "case_key": "lint",
                "position": 1,
                "method_id": "command",
                "instructions": "Run the registered lint command.",
                "expected_outcome": "The command exits successfully.",
                "method_config": {"command": "ruff check ."},
            }],
        )
        for plan in (release, lint):
            set_project_default(
                conn,
                plan_id=plan["id"],
                workflow_id=str(item["workflow_id"]),
                transition_id="release",
            )
        materialized = materialize_for_item(
            conn,
            item_id=42,
            transition_id="release",
        )

    assert set(materialized["plan_ids"]) == {release["id"], lint["id"]}
    assert len(materialized["created_requirement_ids"]) == 3


def test_materialization_is_idempotent_and_preserves_case_snapshot() -> None:
    with test_database() as conn:
        item = insert_item(
            conn,
            id=42,
            title="Ship checkout",
            workflow_id="issue",
            status="implemented",
        )
        plan = _plan(conn)
        set_project_default(
            conn,
            plan_id=plan["id"],
            workflow_id=str(item["workflow_id"]),
            transition_id="release",
        )
        first = materialize_for_item(
            conn, item_id=42, transition_id="release",
        )
        replace_plan_cases(
            conn,
            plan_id=plan["id"],
            cases=[{
                **CASES[0],
                "instructions": "A later edit for future items.",
            }, CASES[1]],
        )
        second = materialize_for_item(
            conn, item_id=42, transition_id="release",
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
    assert snapshot[0]["instructions"] == CASES[0]["instructions"]
    assert json.loads(snapshot[0]["success_policy"]) == {
        "id": "all-pass",
        "params": {},
    }
    assert snapshot[1]["qa_kind"] == "plan_case"
    assert snapshot[1]["workflow_transition_id"] == "release"


def test_activity_folds_requirement_run_and_artifacts_into_case_outcome() -> None:
    with test_database() as conn:
        insert_item(conn, id=42, title="Ship checkout", workflow_id="issue")
        plan = _plan(conn)
        set_project_default(
            conn,
            plan_id=plan["id"],
            workflow_id="issue",
            transition_id="release",
        )
        materialized = materialize_for_item(
            conn, item_id=42, transition_id="release",
        )
        requirement_id = materialized["created_requirement_ids"][0]
        run = conn.execute(
            "INSERT INTO qa_runs("
            "qa_requirement_id, executor_type, qa_kind, verdict, "
            "case_outcome, created_at"
            ") VALUES (%s, 'worktree_run', 'command', 'pass', "
            "'passed', '2026-07-26T12:00:00Z') RETURNING id",
            (requirement_id,),
        ).fetchone()
        conn.execute(
            "INSERT INTO qa_artifacts("
            "qa_run_id, artifact_type, artifact_handle, created_at"
            ") VALUES (%s, 'output', %s, '2026-07-26T12:00:00Z')",
            (run["id"], '{"kind":"local","path":"output.txt"}'),
        )
        conn.commit()
        activity = list_activity(conn, project="yoke")
        detail = get_plan(conn, plan_id=plan["id"])

    passed = next(row for row in activity if row["case_key"] == "backend-suite")
    assert passed["outcome"] == "passed"
    assert passed["evidence_count"] == 1
    assert passed["method_name"] == "Command"
    assert detail["union"] == {
        "satisfied": False,
        "counts": {"passed": 1, "queued": 1},
    }
