"""Shared execution tests for Command and Browser QA plan cases."""

from __future__ import annotations

from pathlib import Path
from unittest import mock
import json


from runtime.api.fixtures.backlog_inserts import insert_item
from runtime.api.fixtures.pg_testdb import test_database
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain import qa_case_execution
from yoke_core.domain.browser_qa_results import RunResult, ScenarioResult
from yoke_core.domain.handlers import qa_case_execution as case_handlers
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
        "lane_branch": None,
    }


def _materialized_command_requirement(conn) -> int:
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
        cases=[
            {
                "case_key": "backend",
                "position": 1,
                "method_id": "command",
                "instructions": "Run backend checks.",
                "expected_outcome": "The command exits successfully.",
                "method_config": {"command": "printf 'composed-case-output'"},
            }
        ],
    )
    set_project_default(
        conn,
        plan_id=plan["id"],
        workflow_id="issue",
        transition_id="implemented",
    )
    materialized = materialize_for_item(
        conn,
        item_id=42,
        transition_id="implemented",
    )
    return int(materialized["created_requirement_ids"][0])


def _case_request(
    function_id: str,
    requirement_id: int,
    payload: dict,
) -> FunctionCallRequest:
    return FunctionCallRequest(
        function=function_id,
        actor=ActorContext(actor_id="1", session_id=""),
        target=TargetRef(
            kind="qa_requirement",
            qa_requirement_id=requirement_id,
        ),
        payload=payload,
    )


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
                json.dumps(
                    {
                        "steps": [
                            {"action": "navigate", "route": "/login"},
                            {"action": "screenshot", "capture": True},
                        ],
                    }
                ),
                "2026-07-26T00:00:00Z",
            ),
        ).fetchone()
        context = get_case_execution_context(
            conn,
            requirement_id=int(row["id"]),
        )

    assert context["plan_id"] is None
    assert context["case_key"].startswith("ad-hoc-")
    assert context["method_id"] == "browser-inspection"
    assert context["executor_id"] == "browser_substrate"


def test_ci_context_keeps_the_merged_commit_after_lane_release() -> None:
    with test_database() as conn:
        insert_item(conn, id=43, title="Run CI", workflow_id="dash")
        conn.execute(
            "CREATE TABLE item_sections ("
            "item_id INTEGER NOT NULL, section_name TEXT NOT NULL, content TEXT, "
            "ordering INTEGER, source TEXT, created_at TEXT, updated_at TEXT, "
            "PRIMARY KEY(item_id, section_name))"
        )
        conn.execute(
            "INSERT INTO item_sections "
            "(item_id, section_name, content, ordering, source, created_at, updated_at) "
            "VALUES (43, 'Execution Evidence', %s, 190, 'direct-workflow', %s, %s)",
            (
                json.dumps({"commit_sha": "b" * 40}),
                "2026-01-01T00:00:00Z",
                "2026-01-01T00:00:00Z",
            ),
        )
        row = conn.execute(
            "INSERT INTO qa_requirements "
            "(item_id, qa_kind, qa_phase, blocking_mode, requirement_source, "
            "method_id, instructions, expected_outcome, method_config, created_at) "
            "VALUES (43, 'plan_case', 'verification', 'blocking', 'explicit', "
            "'command-ci', 'Run CI.', 'CI passes.', %s, %s) RETURNING id",
            (
                json.dumps({"command": "true", "ci_workflow": "ci.yml"}),
                "2026-01-01T00:00:00Z",
            ),
        ).fetchone()
        conn.commit()
        context = get_case_execution_context(conn, requirement_id=int(row["id"]))

    assert context["lane_commit_sha"] == "b" * 40


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
    actor = ActorContext(actor_id="7", session_id="qa-case-test")

    def dispatch(function_id, requirement_id, payload, *, actor=None):
        calls.append((function_id, requirement_id, payload, actor))
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
            41,
            base_url="https://preview.example",
            actor=actor,
        )

    assert result["verdict"] == "pass"
    assert result["case_outcome"] == "passed"
    assert result["run_id"] == 77
    assert [call[0] for call in calls] == [
        "qa.run.add",
        "qa.artifact.add",
        "qa.run.complete",
    ]
    assert all(call[3] == actor for call in calls)
    assert calls[0][2]["executor_type"] == "worktree_run"
    assert "verdict" not in calls[0][2]
    assert calls[2][2]["verdict"] == "pass"
    handle = calls[1][2]["artifact_handle"]
    assert handle["backend"] == "local"
    assert (
        Path(handle["path"])
        .read_text(encoding="utf-8")
        .find("case-output:https://preview.example")
        >= 0
    )


def test_browser_case_executes_only_the_target_requirement() -> None:
    case = _case(
        "browser-check",
        "browser_substrate",
        {"steps": [{"action": "navigate", "route": "/"}]},
    )
    scenario = ScenarioResult(
        verdict="pass",
        runs=[RunResult(41, "plan_case", "pass", qa_run_id=7)],
        executed=1,
    )
    actor = ActorContext(actor_id="7", session_id="qa-case-test")
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
            41,
            base_url="https://preview.example",
            actor=actor,
        )

    assert result["verdict"] == "pass"
    execute.assert_called_once_with(
        item_id=9,
        project="yoke",
        base_url="https://preview.example",
        expected_branch=None,
        expected_sha=None,
        requirement_id=41,
        actor=actor,
    )


def test_doorman_rerun_composes_case_writes_without_a_harness_claim(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("YOKE_SCRATCH_ROOT", str(tmp_path / "scratch"))
    with test_database() as conn:
        requirement_id = _materialized_command_requirement(conn)
        with mock.patch.object(
            qa_case_execution,
            "_execution_checkout",
            return_value=tmp_path,
        ):
            outcome = case_handlers.handle_case_rerun(
                _case_request(
                    "qa.case.rerun",
                    requirement_id,
                    {},
                )
            )
        run = conn.execute(
            "SELECT executor_type, verdict, case_outcome "
            "FROM qa_runs WHERE qa_requirement_id = %s",
            (requirement_id,),
        ).fetchone()
        artifact_count = conn.execute(
            "SELECT COUNT(*) FROM qa_artifacts a "
            "JOIN qa_runs r ON r.id = a.qa_run_id "
            "WHERE r.qa_requirement_id = %s",
            (requirement_id,),
        ).fetchone()[0]

    assert outcome.primary_success is True
    assert outcome.result_payload["verdict"] == "pass"
    assert tuple(run) == ("worktree_run", "pass", "passed")
    assert int(artifact_count) == 1


def test_doorman_waive_records_operator_rationale_without_a_harness_claim() -> None:
    with test_database() as conn:
        requirement_id = _materialized_command_requirement(conn)
        outcome = case_handlers.handle_case_waive(
            _case_request(
                "qa.case.waive",
                requirement_id,
                {"rationale": "Equivalent external proof was reviewed."},
            )
        )
        row = conn.execute(
            "SELECT waived_at, waiver_rationale, waiver_source "
            "FROM qa_requirements WHERE id = %s",
            (requirement_id,),
        ).fetchone()

    assert outcome.primary_success is True
    assert row[0]
    assert row[1] == "Equivalent external proof was reviewed."
    assert row[2] == "operator"
