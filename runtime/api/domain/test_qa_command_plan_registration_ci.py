"""Registered verification commands route to CI when a project declares one."""

from __future__ import annotations

import json

from runtime.api.fixtures.pg_testdb import test_database
from yoke_core.domain.projects_seed_ci_workflow import (
    CI_WORKFLOW_CAPABILITY_TYPE,
)
from yoke_core.domain.qa_command_plan_registration import (
    CI_COMMAND_METHOD_ID,
    LOCAL_COMMAND_METHOD_ID,
    declared_ci_workflow,
    ensure_registered_command_plan,
)


def _declare_ci_workflow(conn, workflow_file: str) -> None:
    conn.execute(
        "INSERT INTO project_capabilities (project_id, type, settings) "
        "VALUES (1, %s, %s)",
        (CI_WORKFLOW_CAPABILITY_TYPE, json.dumps({"workflow_file": workflow_file})),
    )
    conn.commit()


def _case(conn, plan_id: int) -> dict:
    row = conn.execute(
        "SELECT method_id, method_config, instructions, expected_outcome "
        "FROM qa_plan_cases WHERE plan_id=%s",
        (int(plan_id),),
    ).fetchone()
    return {
        "method_id": row["method_id"],
        "method_config": json.loads(row["method_config"]),
        "instructions": row["instructions"],
        "expected_outcome": row["expected_outcome"],
    }


def test_project_without_a_declared_workflow_keeps_the_local_executor() -> None:
    with test_database() as conn:
        result = ensure_registered_command_plan(
            conn, project_id=1, project="yoke", scope="full",
            command="python3 -m pytest",
        )
        case = _case(conn, result["plan_id"])

    assert result["ci_workflow"] == ""
    assert case["method_id"] == LOCAL_COMMAND_METHOD_ID
    assert "ci_workflow" not in case["method_config"]
    assert case["method_config"]["command"] == "python3 -m pytest"


def test_declared_workflow_routes_repository_scopes_to_ci() -> None:
    with test_database() as conn:
        _declare_ci_workflow(conn, "yoke-ci.yml")
        result = ensure_registered_command_plan(
            conn, project_id=1, project="yoke", scope="full",
            command="python3 -m pytest",
        )
        case = _case(conn, result["plan_id"])

    assert result["ci_workflow"] == "yoke-ci.yml"
    assert case["method_id"] == CI_COMMAND_METHOD_ID
    assert case["method_config"]["ci_workflow"] == "yoke-ci.yml"
    # The command is retained: it is what the local fallback executes and
    # what the CI workflow is expected to be running.
    assert case["method_config"]["command"] == "python3 -m pytest"
    assert "CI" in case["instructions"] or "CI" in case["expected_outcome"]


def test_quick_scope_routes_to_ci_alongside_full() -> None:
    with test_database() as conn:
        _declare_ci_workflow(conn, "yoke-ci.yml")
        result = ensure_registered_command_plan(
            conn, project_id=1, project="yoke", scope="quick",
            command="python3 -m pytest --impacted main",
        )
        case = _case(conn, result["plan_id"])

    assert case["method_id"] == CI_COMMAND_METHOD_ID


def test_deployed_environment_scopes_stay_local() -> None:
    # e2e and smoke assert against a running site behind a base URL that a
    # CI workflow has no access to, so a declaration must not move them.
    with test_database() as conn:
        _declare_ci_workflow(conn, "yoke-ci.yml")
        for scope in ("e2e", "smoke"):
            result = ensure_registered_command_plan(
                conn, project_id=1, project="yoke", scope=scope,
                command="python3 -m pytest tests/e2e",
            )
            case = _case(conn, result["plan_id"])

            assert result["ci_workflow"] == ""
            assert case["method_id"] == LOCAL_COMMAND_METHOD_ID


def test_re_registration_moves_an_existing_plan_onto_ci() -> None:
    with test_database() as conn:
        first = ensure_registered_command_plan(
            conn, project_id=1, project="yoke", scope="full",
            command="python3 -m pytest",
        )
        assert _case(conn, first["plan_id"])["method_id"] == (
            LOCAL_COMMAND_METHOD_ID
        )

        _declare_ci_workflow(conn, "yoke-ci.yml")
        second = ensure_registered_command_plan(
            conn, project_id=1, project="yoke", scope="full",
            command="python3 -m pytest",
        )
        case = _case(conn, second["plan_id"])

    assert second["plan_id"] == first["plan_id"]
    assert case["method_id"] == CI_COMMAND_METHOD_ID


def test_declared_workflow_read_tolerates_a_malformed_settings_payload() -> None:
    with test_database() as conn:
        conn.execute(
            "INSERT INTO project_capabilities (project_id, type, settings) "
            "VALUES (1, %s, %s)",
            (CI_WORKFLOW_CAPABILITY_TYPE, "not json"),
        )
        conn.commit()

        assert declared_ci_workflow(conn, 1) == ""


def test_declared_workflow_read_is_empty_without_a_capability_row() -> None:
    with test_database() as conn:
        assert declared_ci_workflow(conn, 1) == ""
