"""Registered command to executable QA-plan registration tests."""

from __future__ import annotations

import json

from runtime.api.fixtures.pg_testdb import test_database
from yoke_core.domain.projects_seed_ci_workflow import CI_WORKFLOW_CAPABILITY_TYPE
from yoke_core.domain.qa_command_plan_convergence import (
    converge_registered_command_plans,
)
from yoke_core.domain.qa_command_plan_registration import (
    CI_COMMAND_METHOD_ID,
    LOCAL_COMMAND_METHOD_ID,
    ensure_registered_command_plan,
)
from yoke_core.domain.qa_plan_project_defaults import set_project_default


def test_current_model_seed_converges_without_legacy_settings() -> None:
    with test_database() as conn:
        first = ensure_registered_command_plan(
            conn,
            project_id=1,
            project="yoke",
            scope="full",
            command="python3 -m pytest",
        )
        second = ensure_registered_command_plan(
            conn,
            project_id=1,
            project="yoke",
            scope="full",
            command="python3 -m pytest",
        )
        legacy = conn.execute(
            "SELECT COUNT(*) FROM project_structure "
            "WHERE family='command_definitions'"
        ).fetchone()[0]
        defaults = conn.execute(
            "SELECT workflow_id, transition_id "
            "FROM qa_plan_project_defaults WHERE plan_id=%s",
            (int(first["plan_id"]),),
        ).fetchall()

    assert second["plan_id"] == first["plan_id"]
    assert legacy == 0
    assert defaults == []


def test_convergence_removes_retired_full_suite_lifecycle_defaults() -> None:
    with test_database() as conn:
        registered = ensure_registered_command_plan(
            conn,
            project_id=1,
            project="yoke",
            scope="full",
            command="python3 -m pytest",
        )
        for workflow_id, transition_id in {
            "blitz": "done",
            "dash": "done",
            "epic": "reviewed-implementation",
            "issue": "reviewed-implementation",
        }.items():
            set_project_default(
                conn,
                plan_id=int(registered["plan_id"]),
                workflow_id=workflow_id,
                transition_id=transition_id,
            )

        converged = converge_registered_command_plans(conn)
        defaults = conn.execute(
            "SELECT workflow_id, transition_id "
            "FROM qa_plan_project_defaults WHERE plan_id=%s",
            (int(registered["plan_id"]),),
        ).fetchall()

    assert converged == [
        {
            "project": "yoke",
            "scope": "full",
            "method_id": "command",
            "ci_workflow": "",
        }
    ]
    assert defaults == []


def _declare(conn, settings: dict) -> None:
    conn.execute(
        "INSERT INTO project_capabilities (project_id, type, settings) "
        "VALUES (1, %s, %s)",
        (CI_WORKFLOW_CAPABILITY_TYPE, json.dumps(settings)),
    )
    conn.commit()


def _case(conn, plan_id: int) -> dict:
    row = conn.execute(
        "SELECT method_id, method_config FROM qa_plan_cases WHERE plan_id=%s",
        (int(plan_id),),
    ).fetchone()
    return {
        "method_id": row["method_id"],
        "method_config": json.loads(row["method_config"]),
    }


def test_a_project_can_declare_a_deployed_scope_reachable_from_ci() -> None:
    """The project, not the scope table, decides whether CI can reach a site."""
    with test_database() as conn:
        _declare(
            conn,
            {"workflow_file": "ci.yml", "scope_workflows": {"smoke": "post-deploy.yml"}},
        )
        result = ensure_registered_command_plan(
            conn, project_id=1, project="yoke", scope="smoke",
            command="npx playwright test",
        )
        case = _case(conn, result["plan_id"])

    assert result["ci_workflow"] == "post-deploy.yml"
    assert case["method_id"] == CI_COMMAND_METHOD_ID


def test_a_declared_scope_dispatches_its_own_workflow_not_the_default() -> None:
    """The per-scope mapping wins over the project's default workflow."""
    with test_database() as conn:
        _declare(
            conn,
            {"workflow_file": "ci.yml", "scope_workflows": {"smoke": "post-deploy.yml"}},
        )
        smoke = ensure_registered_command_plan(
            conn, project_id=1, project="yoke", scope="smoke",
            command="npx playwright test",
        )
        full = ensure_registered_command_plan(
            conn, project_id=1, project="yoke", scope="full",
            command="python3 -m pytest",
        )
        smoke_case = _case(conn, smoke["plan_id"])
        full_case = _case(conn, full["plan_id"])

    assert smoke_case["method_config"]["ci_workflow"] == "post-deploy.yml"
    assert full_case["method_config"]["ci_workflow"] == "ci.yml"


def test_an_undeclared_deployed_scope_keeps_the_local_runner() -> None:
    """A project that maps nothing keeps today's behavior exactly."""
    with test_database() as conn:
        _declare(conn, {"workflow_file": "ci.yml"})
        result = ensure_registered_command_plan(
            conn, project_id=1, project="yoke", scope="smoke",
            command="npx playwright test",
        )
        case = _case(conn, result["plan_id"])

    assert result["ci_workflow"] == ""
    assert case["method_id"] == LOCAL_COMMAND_METHOD_ID


def test_converge_leaves_a_declared_deployed_scope_alone() -> None:
    """A converged run over a correctly declared project writes nothing."""
    with test_database() as conn:
        _declare(
            conn,
            {"workflow_file": "ci.yml", "scope_workflows": {"smoke": "post-deploy.yml"}},
        )
        ensure_registered_command_plan(
            conn, project_id=1, project="yoke", scope="smoke",
            command="npx playwright test",
        )

        converged = converge_registered_command_plans(conn)

    assert converged == []


def test_converge_no_longer_reverts_a_declared_deployed_scope() -> None:
    """The revert regression: the binding survives a schema refresh.

    Before a project could declare its own routing, the converge rewrote every
    deployed-environment binding back to the local runner on the next refresh —
    silently, and only visible later as a gate nobody could satisfy.
    """
    with test_database() as conn:
        registered = ensure_registered_command_plan(
            conn, project_id=1, project="yoke", scope="smoke",
            command="npx playwright test",
        )
        _declare(
            conn,
            {"workflow_file": "ci.yml", "scope_workflows": {"smoke": "post-deploy.yml"}},
        )

        first = converge_registered_command_plans(conn)
        second = converge_registered_command_plans(conn)
        case = _case(conn, registered["plan_id"])

    assert first == [
        {
            "project": "yoke",
            "scope": "smoke",
            "method_id": CI_COMMAND_METHOD_ID,
            "ci_workflow": "post-deploy.yml",
        }
    ]
    assert second == []
    assert case["method_id"] == CI_COMMAND_METHOD_ID


def test_converge_still_corrects_a_binding_that_disagrees() -> None:
    """Dropping the declaration rebinds the scope back to the local runner."""
    with test_database() as conn:
        registered = ensure_registered_command_plan(
            conn, project_id=1, project="yoke", scope="smoke",
            command="npx playwright test",
        )
        _declare(
            conn,
            {"workflow_file": "ci.yml", "scope_workflows": {"smoke": "post-deploy.yml"}},
        )
        converge_registered_command_plans(conn)
        conn.execute(
            "UPDATE project_capabilities SET settings=%s WHERE project_id=1 AND type=%s",
            (json.dumps({"workflow_file": "ci.yml"}), CI_WORKFLOW_CAPABILITY_TYPE),
        )
        conn.commit()

        converged = converge_registered_command_plans(conn)
        case = _case(conn, registered["plan_id"])

    assert converged == [
        {
            "project": "yoke",
            "scope": "smoke",
            "method_id": LOCAL_COMMAND_METHOD_ID,
            "ci_workflow": "",
        }
    ]
    assert case["method_id"] == LOCAL_COMMAND_METHOD_ID
