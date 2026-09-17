"""A case outside a plan still executes, and still names where it ran.

Two facts used to be reachable only through a plan: the position a case
holds in its execution order, and the environment its evidence came from.
An ad-hoc case has neither column filled, so the roster refused it as an
incomplete snapshot and the execution refused it as targetless -- which
left every plan-less case unable to reach a verdict at all.

Neither guard is relaxed for a case that does belong to a plan, and a case
bound to an environment is held to that environment's own address: an
execution target carrying identity and no endpoint would say the
environment is registered, never that the screenshots came from it.
"""

from __future__ import annotations

import json

import pytest

from runtime.api.fixtures.backlog_inserts import insert_item
from runtime.api.fixtures.backlog_qa_inserts import insert_qa_requirement
from runtime.api.fixtures.pg_testdb import test_database
from yoke_core.domain.qa_case_execution_context import (
    QaCaseExecutionError,
    get_case_execution_context,
)
from yoke_core.domain.qa_plan_execution_result_state import QaPlanExecutionError
from yoke_core.domain.qa_plan_execution_roster import ordered_plan_requirements

TRANSITION = "implemented"
PREVIEW_URL = "http://127.0.0.1:8931"


def _browser_case(conn, *, item_id: int, **columns):
    columns.setdefault("qa_kind", "method_case")
    return insert_qa_requirement(
        conn,
        item_id=item_id,
        method_id="browser-inspection",
        method_name="Browser inspection",
        runner_id="browser_substrate",
        verdict_path="agent",
        capability_requirements=json.dumps(["browser"]),
        workflow_transition_id=TRANSITION,
        **columns,
    )


def _environment(conn, *, name: str, url: str | None = None, settings: str = "{}"):
    site = conn.execute(
        "INSERT INTO sites (project_id, name, created_at) "
        "VALUES (1, %s, %s) RETURNING id",
        (f"site-{name}", "2026-09-17T00:00:00Z"),
    ).fetchone()[0]
    conn.execute(
        "INSERT INTO environments (site, project_id, name, url, settings, "
        "created_at) VALUES (%s, 1, %s, %s, %s, %s)",
        (int(site), name, url, settings, "2026-09-17T00:00:00Z"),
    )
    conn.commit()


def test_planless_cases_take_a_stable_order_from_the_roster() -> None:
    with test_database() as conn:
        insert_item(conn, id=6301, title="Ad hoc verified item")
        first = _browser_case(conn, item_id=6301)
        second = _browser_case(conn, item_id=6301)

        roster = ordered_plan_requirements(
            conn, item_id=6301, transition_id=TRANSITION
        )

        # Nothing ever assigned these cases a position inside a plan, so the
        # roster derives one from the order it already selects them in.
        assert [row["requirement_id"] for row in roster] == [
            int(first["id"]),
            int(second["id"]),
        ]
        assert [row["case_position"] for row in roster] == [1, 2]
        assert [row["baseline_position"] for row in roster] == [1, 1]
        assert [row["plan_id"] for row in roster] == [None, None]


def test_a_plan_bound_case_missing_its_positions_is_still_refused() -> None:
    with test_database() as conn:
        insert_item(conn, id=6302, title="Plan verified item")
        plan_id = conn.execute(
            "INSERT INTO qa_plans (project_id, slug, name, created_at, updated_at) "
            "VALUES (1, 'verification', 'Verification', %s, %s) RETURNING id",
            ("2026-09-17T00:00:00Z", "2026-09-17T00:00:00Z"),
        ).fetchone()[0]
        conn.commit()
        _browser_case(
            conn,
            item_id=6302,
            plan_id=int(plan_id),
            plan_case_key="inspect",
            qa_kind="plan_case",
        )

        with pytest.raises(QaPlanExecutionError, match="incomplete"):
            ordered_plan_requirements(
                conn, item_id=6302, transition_id=TRANSITION
            )


def test_a_planless_case_binds_the_environment_it_names() -> None:
    with test_database() as conn:
        insert_item(conn, id=6303, title="Reviewed locally")
        _environment(
            conn,
            name="local",
            settings=json.dumps({"hosts": {"app": PREVIEW_URL}}),
        )
        requirement = _browser_case(
            conn,
            item_id=6303,
            target_env="local",
            method_config=json.dumps({"base_url": PREVIEW_URL}),
        )

        context = get_case_execution_context(
            conn, requirement_id=int(requirement["id"])
        )

        target = context["execution_target"]
        assert target["environment"] == {"name": "local"}
        assert target["endpoints"]["app_url"] == PREVIEW_URL
        assert context["execution_target_digest"]


def test_an_environment_with_no_address_cannot_hold_a_case() -> None:
    with test_database() as conn:
        insert_item(conn, id=6304, title="Reviewed nowhere")
        _environment(conn, name="local")
        requirement = _browser_case(conn, item_id=6304, target_env="local")

        with pytest.raises(QaCaseExecutionError, match="no reviewable URL"):
            get_case_execution_context(conn, requirement_id=int(requirement["id"]))


def test_a_case_browsing_another_address_is_refused() -> None:
    with test_database() as conn:
        insert_item(conn, id=6305, title="Reviewed elsewhere")
        _environment(
            conn,
            name="local",
            settings=json.dumps({"hosts": {"app": PREVIEW_URL}}),
        )
        requirement = _browser_case(
            conn,
            item_id=6305,
            target_env="local",
            method_config=json.dumps({"base_url": "http://127.0.0.1:9999"}),
        )

        with pytest.raises(QaCaseExecutionError, match="not the 'local' target"):
            get_case_execution_context(conn, requirement_id=int(requirement["id"]))


def test_a_case_naming_no_environment_keeps_running_untargeted() -> None:
    with test_database() as conn:
        insert_item(conn, id=6306, title="Runs on this machine")
        requirement = _browser_case(conn, item_id=6306)

        context = get_case_execution_context(
            conn, requirement_id=int(requirement["id"])
        )

        # An item's own verification case names no environment and never
        # did; binding one is what a case opts into, not a new admission bar.
        assert "execution_target" not in context
