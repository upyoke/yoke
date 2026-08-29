"""Materialization ordering and client plan-execution coverage."""

from __future__ import annotations

import json
from unittest import mock

from runtime.api.domain.qa_plan_execution_test_support import (
    TEST_ITEM_ID,
    TEST_ITEM_REF,
)
from runtime.api.fixtures.backlog_inserts import insert_item
from runtime.api.fixtures.pg_testdb import test_database
from yoke_contracts.api.function_call import ActorContext
from yoke_core.domain import (
    machine_qa_case_execution,
    qa_case_execution,
    qa_plan_execution,
)
from yoke_core.domain.qa_case_execution_context import get_case_execution_context
from yoke_core.domain.qa_plan_attachments import (
    materialize_for_item,
    set_project_default,
)
from yoke_core.domain.qa_plan_management import (
    create_plan,
    replace_plan_cases,
)


def _command_case(key: str, position: int) -> dict:
    return {
        "case_key": key,
        "position": position,
        "method_id": "command",
        "instructions": f"Run {key}.",
        "expected_outcome": f"{key} passes.",
        "method_config": {"command": "true"},
    }


def test_materialized_case_context_carries_immutable_runner_snapshot() -> None:
    with test_database() as conn:
        insert_item(
            conn,
            id=TEST_ITEM_ID,
            title="Run verification",
            workflow_id="issue",
        )
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
                    "instructions": "Run backend tests.",
                    "expected_outcome": "The suite exits successfully.",
                    "method_config": {"command": "python3 -m pytest"},
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
            item_id=TEST_ITEM_ID,
            transition_id="implemented",
        )
        requirement_id = materialized["created_requirement_ids"][0]
        conn.execute(
            "UPDATE qa_plan_cases SET position=9, instructions='Mutated', "
            "method_config=%s WHERE plan_id=%s AND case_key='backend'",
            (json.dumps({"command": "false"}), int(plan["id"])),
        )
        conn.execute(
            "UPDATE qa_methods SET name='Mutated method', "
            "runner_id='browser_substrate', verdict_path='agent' "
            "WHERE id='command'"
        )
        context = get_case_execution_context(
            conn,
            requirement_id=requirement_id,
        )
        snapshot = conn.execute(
            "SELECT case_position, baseline_position, method_name, "
            "runner_id, verdict_path FROM qa_requirements WHERE id=%s",
            (requirement_id,),
        ).fetchone()

    assert context["method_id"] == "command"
    assert context["method_name"] == "Command"
    assert context["runner_id"] == "worktree_run"
    assert context["verdict_path"] == "automatic"
    assert context["case_key"] == "backend"
    assert context["instructions"] == "Run backend tests."
    assert context["method_config"] == {"command": "python3 -m pytest"}
    assert tuple(snapshot) == (1, 1, "Command", "worktree_run", "automatic")


def test_stage_order_survives_catalog_reordering_and_baseline_edits() -> None:
    with test_database() as conn:
        insert_item(
            conn,
            id=TEST_ITEM_ID,
            title="Run release QA",
            workflow_id="issue",
        )
        first = create_plan(
            conn,
            project="yoke",
            slug="first-plan",
            name="First plan",
        )
        replace_plan_cases(
            conn,
            plan_id=first["id"],
            cases=[
                {
                    "case_key": "browser",
                    "position": 1,
                    "method_id": "browser-check",
                    "instructions": "Inspect both baselines.",
                    "expected_outcome": "The page passes.",
                    "method_config": {
                        "steps": [
                            {"action": "navigate", "route": "/"},
                            {
                                "action": "assert",
                                "target": "main",
                                "check": "visible",
                            },
                        ],
                    },
                    "host_baselines": [
                        "shell-preconfigured",
                        "fresh-host",
                    ],
                },
                _command_case("command", 2),
            ],
        )
        second = create_plan(
            conn,
            project="yoke",
            slug="second-plan",
            name="Second plan",
        )
        replace_plan_cases(
            conn,
            plan_id=second["id"],
            cases=[_command_case("final", 1)],
        )
        for plan_id in (first["id"], second["id"]):
            set_project_default(
                conn,
                plan_id=plan_id,
                workflow_id="issue",
                transition_id="implemented",
            )
        materialize_for_item(
            conn,
            item_id=TEST_ITEM_ID,
            transition_id="implemented",
        )
        before = qa_plan_execution.ordered_plan_requirements(
            conn,
            item_id=TEST_ITEM_ID,
            transition_id="implemented",
        )
        conn.execute(
            "UPDATE qa_plan_cases SET position=8, host_baselines='[]' "
            "WHERE plan_id=%s AND case_key='browser'",
            (int(first["id"]),),
        )
        conn.execute(
            "UPDATE qa_methods SET runner_id='host_control' WHERE id='browser-check'"
        )
        after = qa_plan_execution.ordered_plan_requirements(
            conn,
            item_id=TEST_ITEM_ID,
            transition_id="implemented",
        )

    assert after == before
    assert [
        (
            row["plan_id"],
            row["case_key"],
            row["case_position"],
            row["baseline_position"],
        )
        for row in before
    ] == [
        (int(first["id"]), "browser", 1, 1),
        (int(first["id"]), "browser", 1, 2),
        (int(first["id"]), "command", 2, 1),
        (int(second["id"]), "final", 1, 1),
    ]


def test_client_runner_preserves_order_and_actor_until_waiting() -> None:
    actor = ActorContext(actor_id="7", session_id="ordered-plan")
    requirements = [
        {
            "requirement_id": 11,
            "plan_id": 3,
            "case_key": "command",
            "case_position": 1,
            "baseline_position": 1,
            "host_baseline": None,
            "runner_id": "worktree_run",
        },
        {
            "requirement_id": 12,
            "plan_id": 3,
            "case_key": "browser",
            "case_position": 2,
            "baseline_position": 1,
            "host_baseline": None,
            "runner_id": "browser_substrate",
        },
        {
            "requirement_id": 13,
            "plan_id": 4,
            "case_key": "machine",
            "case_position": 1,
            "baseline_position": 1,
            "host_baseline": "fresh-host",
            "runner_id": "host_control",
        },
        {
            "requirement_id": 14,
            "plan_id": 4,
            "case_key": "not-reached",
            "case_position": 2,
            "baseline_position": 1,
            "host_baseline": None,
            "runner_id": "worktree_run",
        },
    ]
    outcomes = {
        11: {"requirement_id": 11, "verdict": "pass"},
        12: {"requirement_id": 12, "verdict": "fail"},
        13: {
            "requirement_id": 13,
            "verdict": "waiting",
            "case_outcome": "waiting",
        },
    }

    function_calls: list[tuple[str, dict, ActorContext]] = []

    def call_plan_function(**kwargs):
        function_calls.append(
            (kwargs["function_id"], kwargs["payload"], kwargs["actor"])
        )
        if kwargs["function_id"] == "qa.plan_execution.begin":
            return {
                "execution_id": "plan-execution-1",
                "item_id": TEST_ITEM_ID,
                "transition_id": "implemented",
                "state": "active",
                "roster_digest": "digest",
                "cursor_ordinal": 0,
                "execution_target": {
                    "environment": {"name": "development"},
                    "endpoints": {
                        "app_url": "",
                        "api_url": "",
                    },
                },
                "execution_target_digest": "target-digest",
                "requirements": requirements,
                "results": [],
            }
        return {}

    with (
        mock.patch.object(
            qa_plan_execution,
            "_call_plan_function",
            side_effect=call_plan_function,
        ),
        mock.patch.object(
            qa_case_execution,
            "execute_case_context",
            side_effect=lambda case, **_kwargs: outcomes[case["requirement_id"]],
        ) as execute,
        mock.patch.object(
            machine_qa_case_execution,
            "execute_materialized_machine_baseline_group",
            return_value={
                "anchor_requirement_id": 13,
                "baseline_ok": None,
                "requirement_ids": [13],
                "results": [outcomes[13]],
            },
        ) as execute_group,
    ):
        result = qa_plan_execution.execute_plan(
            public_ref=TEST_ITEM_REF,
            transition_id="implemented",
            actor=actor,
        )

    assert result["state"] == "waiting"
    assert result["requirement_count"] == 4
    assert result["executed_count"] == 3
    assert [call.args[0]["requirement_id"] for call in execute.call_args_list] == [
        11,
        12,
    ]
    assert all(call.kwargs["actor"] == actor for call in execute.call_args_list)
    execute_group.assert_called_once_with(
        requirements[2],
        actor=actor,
    )
    assert [function for function, _payload, _actor in function_calls] == [
        "qa.plan_execution.begin",
        "qa.plan_execution.heartbeat",
        "qa.plan_execution.advance",
        "qa.plan_execution.heartbeat",
        "qa.plan_execution.advance",
        "qa.plan_execution.heartbeat",
    ]
    assert all(
        call_actor == actor for _function, _payload, call_actor in function_calls
    )
