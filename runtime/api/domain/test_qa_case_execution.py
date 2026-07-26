"""Shared execution tests for Command and Browser QA plan cases."""

from __future__ import annotations

from pathlib import Path
from unittest import mock
import json

from runtime.api.fixtures.backlog_inserts import insert_item
from runtime.api.fixtures.pg_testdb import test_database
from yoke_core.domain import qa_case_execution
from yoke_core.domain.browser_qa_results import RunResult, ScenarioResult
from yoke_core.domain.qa_case_execution_context import (
    get_case_execution_context,
)
from yoke_core.domain.qa_plan_attachments import (
    materialize_for_item,
    set_project_default,
)
from yoke_core.domain.qa_plan_management import create_plan, replace_plan_cases


def _case(method_id: str, executor_id: str, config: dict) -> dict:
    return {
        "requirement_id": 41,
        "item_id": 9,
        "plan_id": 5,
        "case_key": "registered",
        "method_id": method_id,
        "executor_id": executor_id,
        "method_config": config,
        "project_id": 1,
        "project": "yoke",
        "worktree": None,
    }


def test_materialized_case_context_carries_immutable_executor_snapshot() -> None:
    with test_database() as conn:
        insert_item(conn, id=42, title="Run verification", workflow_id="issue")
        plan = create_plan(
            conn,
            project="yoke",
            slug="command-verification",
            name="Command verification",
        )
        replace_plan_cases(
            conn,
            plan_id=plan["id"],
            cases=[{
                "case_key": "backend",
                "position": 1,
                "method_id": "command",
                "instructions": "Run backend tests.",
                "expected_outcome": "The suite exits successfully.",
                "method_config": {"command": "python3 -m pytest"},
            }],
        )
        set_project_default(
            conn,
            plan_id=plan["id"],
            workflow_id="issue",
            transition_id="implemented",
        )
        materialized = materialize_for_item(
            conn, item_id=42, transition_id="implemented",
        )
        context = get_case_execution_context(
            conn,
            requirement_id=materialized["created_requirement_ids"][0],
        )

    assert context["method_id"] == "command"
    assert context["executor_id"] == "worktree_run"
    assert context["case_key"] == "backend"
    assert context["method_config"] == {"command": "python3 -m pytest"}


def test_ad_hoc_method_case_uses_the_same_execution_context() -> None:
    with test_database() as conn:
        insert_item(conn, id=42, title="Inspect login", workflow_id="issue")
        row = conn.execute(
            "INSERT INTO qa_requirements("
            "item_id, qa_kind, qa_phase, blocking_mode, requirement_source, "
            "method_id, instructions, expected_outcome, method_config, "
            "created_at"
            ") VALUES (42, 'method_case', 'verification', 'blocking', "
            "'explicit', 'browser-inspection', %s, %s, %s, %s) RETURNING id",
            (
                "Capture the login page.",
                "The form is visually aligned.",
                json.dumps({
                    "steps": [
                        {"action": "navigate", "route": "/login"},
                        {"action": "screenshot", "capture": True},
                    ],
                }),
                "2026-07-26T00:00:00Z",
            ),
        ).fetchone()
        context = get_case_execution_context(
            conn, requirement_id=int(row["id"]),
        )

    assert context["plan_id"] is None
    assert context["case_key"].startswith("ad-hoc-")
    assert context["method_id"] == "browser-inspection"
    assert context["executor_id"] == "browser_substrate"


def test_command_case_records_verdict_and_output_artifact(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("YOKE_SCRATCH_ROOT", str(tmp_path / "scratch"))
    case = _case(
        "command",
        "worktree_run",
        {
            "command": "printf 'case-output:%s' \"$BASE_URL\"",
            "requires_base_url": True,
        },
    )
    calls = []

    def dispatch(function_id, requirement_id, payload):
        calls.append((function_id, requirement_id, payload))
        if function_id == "qa.run.add":
            return {"qa_run_id": 77}
        if function_id == "qa.artifact.add":
            return {"qa_artifact_id": 88}
        if function_id == "qa.run.complete":
            return {"qa_run_id": 77}
        raise AssertionError(function_id)

    with (
        mock.patch.object(
            qa_case_execution,
            "fetch_case_execution_context",
            return_value=case,
        ),
        mock.patch.object(
            qa_case_execution,
            "_execution_checkout",
            return_value=tmp_path,
        ),
        mock.patch.object(
            qa_case_execution,
            "_dispatch",
            side_effect=dispatch,
        ),
    ):
        result = qa_case_execution.execute_case(
            41, base_url="https://preview.example",
        )

    assert result["verdict"] == "pass"
    assert result["case_outcome"] == "passed"
    assert result["run_id"] == 77
    assert [call[0] for call in calls] == [
        "qa.run.add", "qa.artifact.add", "qa.run.complete",
    ]
    assert calls[0][2]["executor_type"] == "worktree_run"
    assert "verdict" not in calls[0][2]
    assert calls[2][2]["verdict"] == "pass"
    handle = calls[1][2]["artifact_handle"]
    assert handle["backend"] == "local"
    assert Path(handle["path"]).read_text(encoding="utf-8").find(
        "case-output:https://preview.example"
    ) >= 0


def test_browser_case_executes_only_the_target_requirement() -> None:
    case = _case(
        "browser-check",
        "browser_substrate",
        {"steps": [{"action": "navigate", "route": "/"}]},
    )
    scenario = ScenarioResult(
        verdict="pass",
        runs=[RunResult(41, "browser_smoke", "pass", qa_run_id=7)],
        executed=1,
    )
    with (
        mock.patch.object(
            qa_case_execution,
            "fetch_case_execution_context",
            return_value=case,
        ),
        mock.patch(
            "yoke_core.domain.browser_qa.execute_scenario",
            return_value=scenario,
        ) as execute,
    ):
        result = qa_case_execution.execute_case(
            41, base_url="https://preview.example",
        )

    assert result["verdict"] == "pass"
    execute.assert_called_once_with(
        item_id=9,
        project="yoke",
        base_url="https://preview.example",
        expected_branch=None,
        expected_sha=None,
        requirement_id=41,
    )
