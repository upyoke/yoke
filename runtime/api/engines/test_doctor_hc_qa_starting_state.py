"""HC-qa-plan-machine-starting-state fails on a stored plan that cannot materialize."""

from __future__ import annotations

from runtime.api.fixtures.pg_testdb import test_database
from yoke_core.domain.qa_plan_management import create_plan, replace_plan_cases
from yoke_core.engines.doctor_hc_qa_starting_state import (
    hc_qa_plan_starting_state,
)
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector


def _machine_case(key: str, position: int, **start) -> dict:
    return {
        "case_key": key,
        "position": position,
        "method_id": "machine-state-check",
        "instructions": "Check the host.",
        "expected_outcome": "The check passes.",
        "method_config": {"assertions": [{"argv": ["/usr/bin/true"]}]},
        **start,
    }


def _run(conn) -> tuple[str, str]:
    rec = RecordCollector()
    hc_qa_plan_starting_state(conn, DoctorArgs(), rec)
    (result,) = rec.results
    return result.result, result.detail


def _declared_plan(conn, slug: str) -> dict:
    plan = create_plan(conn, project="yoke", slug=slug)
    replace_plan_cases(
        conn,
        plan_id=plan["id"],
        cases=[
            _machine_case("open", 1, host_baselines=["fresh-host"]),
            _machine_case("follow", 2, starting_state="inherit"),
        ],
    )
    return plan


def test_declared_plans_pass() -> None:
    with test_database() as conn:
        _declared_plan(conn, "declared")
        verdict, detail = _run(conn)
    assert (verdict, detail) == ("PASS", "")


def test_stored_undeclared_case_fails_with_its_plan_and_recovery() -> None:
    with test_database() as conn:
        plan = _declared_plan(conn, "stored-undeclared")
        # A case stored before the contract required a declaration.
        conn.execute(
            "UPDATE qa_plan_cases SET host_baselines='[]', starting_state=NULL "
            "WHERE plan_id=%s AND case_key='open'",
            (plan["id"],),
        )
        verdict, detail = _run(conn)
    assert verdict == "FAIL"
    assert f"yoke plan {plan['id']}" in detail
    assert "case 'open' declares no starting state" in detail
    assert "yoke qa plan-cases replace" in detail


def test_retired_plan_is_not_a_finding() -> None:
    with test_database() as conn:
        plan = _declared_plan(conn, "retired-undeclared")
        conn.execute(
            "UPDATE qa_plan_cases SET host_baselines='[]', starting_state=NULL "
            "WHERE plan_id=%s",
            (plan["id"],),
        )
        conn.execute(
            "UPDATE qa_plans SET retired_at='2026-01-01T00:00:00Z' WHERE id=%s",
            (plan["id"],),
        )
        verdict, _ = _run(conn)
    assert verdict == "PASS"
