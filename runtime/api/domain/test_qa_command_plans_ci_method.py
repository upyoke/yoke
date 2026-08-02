"""A project's registered command is readable however it is routed.

Rebinding a registered scope onto the CI method changes *where* the
command runs, not whether the project has one. Every reader of "what
does this project run?" must keep answering — otherwise the polish
gate and the verification health check both conclude the project is
unconfigured the moment its gate moves to CI.
"""

from __future__ import annotations

import json

from runtime.api.fixtures.pg_testdb import test_database
from yoke_core.domain.projects_seed_ci_workflow import (
    CI_WORKFLOW_CAPABILITY_TYPE,
)
from yoke_core.domain.qa_command_plan_registration import (
    CI_COMMAND_METHOD_ID,
    LOCAL_COMMAND_METHOD_ID,
    ensure_registered_command_plan,
)
from yoke_core.domain.qa_command_plans import (
    REGISTERED_COMMAND_METHOD_IDS,
    list_registered_commands_for_project_id,
)


def _declare_ci_workflow(conn) -> None:
    conn.execute(
        "INSERT INTO project_capabilities (project_id, type, settings) "
        "VALUES (1, %s, %s)",
        (CI_WORKFLOW_CAPABILITY_TYPE, json.dumps({"workflow_file": "ci.yml"})),
    )
    conn.commit()


def test_both_command_bindings_are_registered_scopes() -> None:
    assert set(REGISTERED_COMMAND_METHOD_IDS) == {
        LOCAL_COMMAND_METHOD_ID,
        CI_COMMAND_METHOD_ID,
    }


def test_locally_bound_commands_are_listed() -> None:
    with test_database() as conn:
        ensure_registered_command_plan(
            conn, project_id=1, project="yoke", scope="quick",
            command="python3 -m pytest --impacted main",
        )

        commands = list_registered_commands_for_project_id(conn, 1)

    assert commands == {"quick": "python3 -m pytest --impacted main"}


def test_ci_bound_commands_are_still_listed() -> None:
    with test_database() as conn:
        _declare_ci_workflow(conn)
        ensure_registered_command_plan(
            conn, project_id=1, project="yoke", scope="quick",
            command="python3 -m pytest --impacted main",
        )
        ensure_registered_command_plan(
            conn, project_id=1, project="yoke", scope="full",
            command="python3 -m pytest runtime/ tests/",
        )
        bound = conn.execute(
            "SELECT DISTINCT method_id FROM qa_plan_cases c "
            "JOIN qa_plans p ON p.id=c.plan_id WHERE p.project_id=1"
        ).fetchall()

        commands = list_registered_commands_for_project_id(conn, 1)

    assert {row["method_id"] for row in bound} == {CI_COMMAND_METHOD_ID}
    assert commands == {
        "quick": "python3 -m pytest --impacted main",
        "full": "python3 -m pytest runtime/ tests/",
    }


def test_verification_health_check_passes_on_a_ci_bound_project() -> None:
    from yoke_core.engines.doctor_hc_project_verification import (
        CHECK_ID,
        hc_project_verification_configured,
    )

    class _Collector:
        def __init__(self) -> None:
            self.records: list[tuple] = []

        def record(self, check_id, name, status, detail, *args, **kwargs):
            self.records.append((check_id, status, detail))

    with test_database() as conn:
        _declare_ci_workflow(conn)
        ensure_registered_command_plan(
            conn, project_id=1, project="yoke", scope="quick",
            command="python3 -m pytest --impacted main",
        )
        slug = conn.execute(
            "SELECT slug FROM projects WHERE id=1"
        ).fetchone()["slug"]
        collector = _Collector()
        hc_project_verification_configured(conn, None, collector)

    assert collector.records, "the check recorded no result"
    check_id, _, detail = collector.records[0]
    assert check_id == CHECK_ID
    # Other seeded projects may legitimately have no plan; this project's
    # CI-bound case must not read as an inert one.
    assert slug not in detail
