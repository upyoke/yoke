"""Registered verification commands route to CI when a project declares one."""

from __future__ import annotations

import json

from runtime.api.fixtures.pg_testdb import test_database
from yoke_core.domain.migration_restore_point import RESTORE_POINT_ENV
from yoke_core.domain.projects_seed_ci_workflow import (
    CI_WORKFLOW_CAPABILITY_TYPE,
)
from yoke_core.domain.qa_command_plan_convergence import (
    converge_registered_command_plans,
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


def _plan_id(conn, scope: str) -> int:
    row = conn.execute(
        "SELECT id FROM qa_plans WHERE project_id=1 AND slug=%s",
        (f"registered-command-{scope}",),
    ).fetchone()
    return int(row["id"])


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


def test_project_without_a_declared_workflow_keeps_the_local_runner() -> None:
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


def test_converge_rebinds_a_project_that_declared_ci_after_registering() -> None:
    # The live shape this converge exists for: the command was registered
    # first, the capability declared later. Registration alone never runs
    # again, so without a converge the binding stays local forever.
    with test_database() as conn:
        ensure_registered_command_plan(
            conn, project_id=1, project="yoke", scope="quick",
            command="python3 -m pytest --impacted main",
        )
        assert _case(conn, _plan_id(conn, "quick"))["method_id"] == (
            LOCAL_COMMAND_METHOD_ID
        )

        _declare_ci_workflow(conn, "yoke-ci.yml")
        converged = converge_registered_command_plans(conn)
        case = _case(conn, _plan_id(conn, "quick"))

    assert case["method_id"] == CI_COMMAND_METHOD_ID
    assert case["method_config"]["ci_workflow"] == "yoke-ci.yml"
    assert [(row["scope"], row["method_id"]) for row in converged] == [
        ("quick", CI_COMMAND_METHOD_ID)
    ]


def test_converge_writes_nothing_when_bindings_already_agree() -> None:
    with test_database() as conn:
        _declare_ci_workflow(conn, "yoke-ci.yml")
        ensure_registered_command_plan(
            conn, project_id=1, project="yoke", scope="quick",
            command="python3 -m pytest --impacted main",
        )

        assert converge_registered_command_plans(conn) == []


def test_converge_rebinds_back_to_local_when_the_declaration_is_removed() -> None:
    with test_database() as conn:
        _declare_ci_workflow(conn, "yoke-ci.yml")
        ensure_registered_command_plan(
            conn, project_id=1, project="yoke", scope="quick",
            command="python3 -m pytest --impacted main",
        )
        conn.execute(
            "DELETE FROM project_capabilities WHERE project_id=1 AND type=%s",
            (CI_WORKFLOW_CAPABILITY_TYPE,),
        )
        conn.commit()

        converged = converge_registered_command_plans(conn)
        case = _case(conn, _plan_id(conn, "quick"))

    assert case["method_id"] == LOCAL_COMMAND_METHOD_ID
    assert "ci_workflow" not in case["method_config"]
    assert [row["scope"] for row in converged] == ["quick"]


def test_converge_follows_a_changed_workflow_filename() -> None:
    with test_database() as conn:
        _declare_ci_workflow(conn, "yoke-ci.yml")
        ensure_registered_command_plan(
            conn, project_id=1, project="yoke", scope="quick",
            command="python3 -m pytest --impacted main",
        )
        conn.execute(
            "UPDATE project_capabilities SET settings=%s "
            "WHERE project_id=1 AND type=%s",
            (json.dumps({"workflow_file": "renamed-ci.yml"}),
             CI_WORKFLOW_CAPABILITY_TYPE),
        )
        conn.commit()

        converge_registered_command_plans(conn)
        case = _case(conn, _plan_id(conn, "quick"))

    assert case["method_config"]["ci_workflow"] == "renamed-ci.yml"


def test_ensure_canonicalizes_retired_watch_pytest_command() -> None:
    from yoke_core.domain.qa_command_invocation import SANCTIONED_WATCH_PYTEST

    with test_database() as conn:
        ensure_registered_command_plan(
            conn, project_id=1, project="yoke", scope="quick",
            command=(
                "uv run --frozen python3 -m yoke_core.tools.watch_pytest "
                "--impacted main"
            ),
        )
        case = _case(conn, _plan_id(conn, "quick"))

    assert case["method_config"]["command"] == (
        f"{SANCTIONED_WATCH_PYTEST} --impacted main"
    )


def test_converge_rewrites_retired_watch_pytest_plan_command() -> None:
    from yoke_core.domain.qa_command_invocation import SANCTIONED_WATCH_PYTEST

    retired = (
        "uv run --frozen python3 -m yoke_core.tools.watch_pytest "
        "--impacted main"
    )
    with test_database() as conn:
        ensure_registered_command_plan(
            conn, project_id=1, project="yoke", scope="quick",
            command="python3 -m pytest --impacted main",
        )
        plan_id = _plan_id(conn, "quick")
        config = _case(conn, plan_id)["method_config"]
        config["command"] = retired
        conn.execute(
            "UPDATE qa_plan_cases SET method_config=%s WHERE plan_id=%s",
            (json.dumps(config), plan_id),
        )
        conn.commit()

        converged = converge_registered_command_plans(conn)
        case = _case(conn, plan_id)

    assert case["method_config"]["command"] == (
        f"{SANCTIONED_WATCH_PYTEST} --impacted main"
    )
    assert [row["scope"] for row in converged] == ["quick"]


def test_boot_converge_rebinds_registered_command_plans(monkeypatch) -> None:
    # The wiring that makes this reach a live universe at all.
    from yoke_core.domain.schema_init import converge_core_schema

    monkeypatch.setenv(RESTORE_POINT_ENV, "qa-command-plan-test-snapshot")
    with test_database() as conn:
        ensure_registered_command_plan(
            conn, project_id=1, project="yoke", scope="quick",
            command="python3 -m pytest --impacted main",
        )
        _declare_ci_workflow(conn, "yoke-ci.yml")

        converge_core_schema(conn)
        case = _case(conn, _plan_id(conn, "quick"))

    assert case["method_id"] == CI_COMMAND_METHOD_ID
