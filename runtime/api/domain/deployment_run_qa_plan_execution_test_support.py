"""Shared fixtures for deployment-run QA plan execution tests."""

from runtime.api.domain.machine_qa_baseline_group_test_support import (
    _terminal_recipe,
)
from yoke_core.domain.qa_plan_management import (
    create_plan,
    replace_plan_cases,
)


RUN_ID = "run-20260728-901"


def deployment_run(conn) -> None:
    conn.execute(
        "INSERT INTO deployment_flows("
        "id,project_id,name,description,stages,created_at"
        ") VALUES ('qa-release',1,'QA release','', '[]', "
        "'2026-07-28T00:00:00Z')"
    )
    conn.execute(
        "INSERT INTO deployment_runs("
        "id,project_id,flow,status,created_at"
        ") VALUES (%s,1,'qa-release','succeeded',"
        "'2026-07-28T00:00:00Z')",
        (RUN_ID,),
    )
    conn.commit()


def command_plan(conn) -> int:
    plan = create_plan(
        conn,
        project="yoke",
        slug="deployment-smoke",
        name="Deployment smoke",
    )
    replace_plan_cases(
        conn,
        plan_id=int(plan["id"]),
        cases=[
            {
                "case_key": "release-command",
                "position": 1,
                "method_id": "command",
                "instructions": "Run the release check.",
                "expected_outcome": "The release check passes.",
                "method_config": {"command": "true"},
            }
        ],
    )
    return int(plan["id"])


def atomic_command_plan(conn) -> int:
    plan = create_plan(
        conn,
        project="yoke",
        slug="atomic-deployment-smoke",
        name="Atomic deployment smoke",
    )
    replace_plan_cases(
        conn,
        plan_id=int(plan["id"]),
        cases=[
            {
                "case_key": f"release-command-{position}",
                "position": position,
                "method_id": "command",
                "instructions": f"Run release check {position}.",
                "expected_outcome": f"Release check {position} passes.",
                "method_config": {"command": "true"},
            }
            for position in (1, 2)
        ],
    )
    return int(plan["id"])


def machine_plan(conn) -> int:
    plan = create_plan(
        conn,
        project="yoke",
        slug="deployment-machine-smoke",
        name="Deployment Machine smoke",
    )
    replace_plan_cases(
        conn,
        plan_id=int(plan["id"]),
        cases=[
            {
                "case_key": "terminal-release-check",
                "position": 1,
                "method_id": "terminal-check",
                "instructions": "Run one bounded release Terminal check.",
                "expected_outcome": "The Terminal check passes.",
                "method_config": _terminal_recipe(),
                "entry_surface": "printf done",
                "required_completion": "complete",
            }
        ],
    )
    return int(plan["id"])


__all__ = [
    "RUN_ID",
    "atomic_command_plan",
    "command_plan",
    "deployment_run",
    "machine_plan",
]
