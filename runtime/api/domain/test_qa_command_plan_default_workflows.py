"""Registration writes project defaults only for workflows that read them."""

from __future__ import annotations

from runtime.api.fixtures.pg_testdb import test_database
from yoke_core.domain.qa_command_plan_convergence import (
    converge_registered_command_plans,
)
from yoke_core.domain.qa_command_plan_registration import (
    ensure_registered_command_plan,
)
from yoke_core.domain.qa_plan_attachments import PROJECT_DEFAULT_QA_POLICIES
from yoke_core.domain.qa_plan_project_defaults import set_project_default
from yoke_core.domain.workflow_registry import list_current_workflows


def _default_workflows(conn, plan_id: int) -> set[str]:
    return {
        str(row["workflow_id"])
        for row in conn.execute(
            "SELECT workflow_id FROM qa_plan_project_defaults WHERE plan_id=%s",
            (plan_id,),
        ).fetchall()
    }


def _reading_workflows(conn) -> set[str]:
    return {
        str(row["id"])
        for row in list_current_workflows(conn)
        if row["definition"]["policies"].get("qa") in PROJECT_DEFAULT_QA_POLICIES
    }


def test_quick_registration_writes_no_dash_default() -> None:
    with test_database() as conn:
        registered = ensure_registered_command_plan(
            conn, project_id=1, project="yoke", scope="quick", command="true"
        )
        written = _default_workflows(conn, int(registered["plan_id"]))
        reading = _reading_workflows(conn)

    assert "dash" not in written
    assert "dash" not in registered["workflow_ids"]
    assert written
    assert written <= reading


def test_convergence_drops_a_stale_dash_default() -> None:
    with test_database() as conn:
        registered = ensure_registered_command_plan(
            conn, project_id=1, project="yoke", scope="quick", command="true"
        )
        plan_id = int(registered["plan_id"])
        expected = _default_workflows(conn, plan_id)
        set_project_default(
            conn,
            plan_id=plan_id,
            workflow_id="dash",
            transition_id="reviewing-implementation",
        )

        converge_registered_command_plans(conn)
        converged = _default_workflows(conn, plan_id)

    assert converged == expected
