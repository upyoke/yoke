"""A whole-plan edit carries every case field and never resets one unseen."""

from __future__ import annotations

from contextlib import nullcontext
from unittest.mock import patch

from runtime.api.domain.deployment_qa_stage_execution_test_support import _environment
from runtime.api.fixtures.pg_testdb import test_database
from yoke_contracts.api.function_call import FunctionCallRequest
from yoke_contracts.qa_plan_case_document import QA_PLAN_CASE_FIELDS
from yoke_core.domain.handlers.qa_plan_edit import handle_plan_edit
from yoke_core.domain.qa_plan_detail import get_plan
from yoke_core.domain.qa_plan_edit import _current_cases
from yoke_core.domain.qa_plan_management import create_plan, replace_plan_cases

from runtime.api.qa_plan_edit_test_support import _updated_at


def _route(path: str) -> dict:
    return {"command": f"curl -fsS $BASE_URL{path}", "requires_base_url": True}


def _case(key: str, command: str) -> dict:
    return {
        "case_key": key,
        "method_id": "command",
        "instructions": f"Request {command} on the target.",
        "expected_outcome": "The route answers successfully.",
        "method_config": _route(command),
        "target_envs": ["stage", "prod"],
        "stage_reason": "changes_infrastructure",
    }


def _plan(conn) -> dict:
    _environment(conn)
    conn.execute(
        "INSERT INTO environments(site,project_id,name,url,settings,created_at) "
        "SELECT id,1,'prod','https://prod.example.test','{\"role\":{\"production\":true}}','2026-09-14T00:00:00Z' "
        "FROM sites WHERE project_id=1 ORDER BY id LIMIT 1 "
        "ON CONFLICT(project_id,name) DO NOTHING"
    )
    plan = create_plan(
        conn,
        project="yoke",
        slug="routes",
        name="Routes",
        target_environment="prod",
    )
    replace_plan_cases(
        conn,
        plan_id=plan["id"],
        cases=[_case("dashboard", "/workflows"), _case("health", "/health")],
    )
    return plan


def _save(conn, plan: dict, cases: list[dict]):
    request = FunctionCallRequest(
        function="qa.plan.edit",
        actor={"session_id": "qa-plan-edit-test"},
        target={"kind": "global"},
        payload={
            "project": "yoke",
            "slug": plan["slug"],
            "base_updated_at": _updated_at(conn, plan["id"]),
            "name": "Routes",
            "target_environment": "prod",
            "cases": cases,
        },
    )
    with patch(
        "yoke_core.domain.db_helpers.connect",
        return_value=nullcontext(conn),
    ):
        return handle_plan_edit(request)


def test_reads_and_the_edit_document_share_one_case_field_set() -> None:
    with test_database() as conn:
        plan = _plan(conn)
        stored = _current_cases(conn, plan["id"])
        detail = get_plan(conn, plan_id=plan["id"])

    assert all(tuple(case) == QA_PLAN_CASE_FIELDS for case in stored)
    assert all(set(QA_PLAN_CASE_FIELDS) <= set(case) for case in detail["cases"])


def test_editing_one_case_route_preserves_every_field_of_every_case() -> None:
    with test_database() as conn:
        plan = _plan(conn)
        before = _current_cases(conn, plan["id"])
        edited = [dict(case) for case in before]
        edited[0]["method_config"] = _route("/orgs/a")
        outcome = _save(conn, plan, edited)
        after = _current_cases(conn, plan["id"])

    assert outcome.primary_success is True, outcome.error
    assert after == edited
    assert [case["target_envs"] for case in after] == [["stage", "prod"]] * 2


def test_a_save_that_would_reset_an_unedited_field_is_refused() -> None:
    with test_database() as conn:
        plan = _plan(conn)
        base = _updated_at(conn, plan["id"])
        before = _current_cases(conn, plan["id"])
        # The document an edit client without target_envs would send.
        edited = [
            {
                key: value
                for key, value in case.items()
                if key not in {"target_envs", "stage_reason"}
            }
            for case in before
        ]
        edited[0]["method_config"] = _route("/orgs/a")
        outcome = _save(conn, plan, edited)
        after = _current_cases(conn, plan["id"])
        after_base = _updated_at(conn, plan["id"])

    assert outcome.primary_success is False and outcome.error is not None
    assert outcome.error.code == "incompatible"
    message = outcome.error.message
    assert message.startswith("qa_plan_edit_unedited_field_changed:")
    assert "case 'dashboard' target_envs" in message
    assert "case 'health' target_envs" in message
    assert "case 'dashboard' stage_reason" in message
    assert "Nothing was saved" in message
    assert "yoke qa plan edit routes --project yoke" in message
    assert after == before and after_base == base


def test_an_omitted_field_that_keeps_its_stored_value_saves() -> None:
    with test_database() as conn:
        plan = _plan(conn)
        before = _current_cases(conn, plan["id"])
        # Fields left at their stored default, plus a brand-new case that
        # states only what it needs: neither resets anything stored.
        edited = [
            {
                key: value
                for key, value in case.items()
                if key not in {"success_policy_params", "host_baselines"}
            }
            for case in before
        ]
        edited.append({**_case("status", "/status"), "position": 3})
        outcome = _save(conn, plan, edited)
        after = _current_cases(conn, plan["id"])

    assert outcome.primary_success is True, outcome.error
    assert after[:2] == before
    assert after[2]["case_key"] == "status"
