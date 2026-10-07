"""Plan authoring, materialization and direct adds refuse undeclared machine cases."""

from __future__ import annotations

import pytest

from runtime.api.fixtures.backlog_inserts import insert_item
from runtime.api.fixtures.pg_testdb import test_database
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain.handlers import qa_requirement_create
from yoke_core.domain.qa_plan_case_definition import plan_cases
from yoke_core.domain.qa_plan_management import (
    QaPlanError,
    create_plan,
    replace_plan_cases,
)
from yoke_core.domain.qa_workflow_binding_validation import item_transition_for_gate
from yoke_core.domain.workflow_gate_catalog import GATE_QA_VERIFICATION

_ASSERTIONS = {"assertions": [{"argv": ["/usr/bin/true"]}]}


def _machine_case(key: str, position: int, **start) -> dict:
    return {
        "case_key": key,
        "position": position,
        "method_id": "machine-state-check",
        "instructions": "Check the host.",
        "expected_outcome": "The check passes.",
        "method_config": dict(_ASSERTIONS),
        **start,
    }


def test_plan_authoring_refuses_an_undeclared_machine_case() -> None:
    with test_database() as conn:
        plan = create_plan(conn, project="yoke", slug="undeclared-machine")
        with pytest.raises(QaPlanError) as refusal:
            replace_plan_cases(
                conn, plan_id=plan["id"], cases=[_machine_case("bare", 1)]
            )
    message = str(refusal.value)
    assert "case 'bare' declares no starting state" in message
    assert "fresh-host, shell-preconfigured" in message


def test_declared_chain_is_stored_and_fans_out_from_its_opening_case() -> None:
    with test_database() as conn:
        plan = create_plan(conn, project="yoke", slug="declared-chain")
        replace_plan_cases(
            conn,
            plan_id=plan["id"],
            cases=[
                _machine_case(
                    "open", 1, host_baselines=["fresh-host", "shell-preconfigured"]
                ),
                _machine_case("follow", 2, starting_state="inherit"),
                _machine_case(
                    "found", 3, starting_state="as_is", starting_state_reason="lab"
                ),
            ],
        )
        cases = {case["case_key"]: case for case in plan_cases(conn, plan["id"])}
    assert cases["open"]["starting_state"] == "baseline"
    assert cases["follow"]["starting_state"] == "inherit"
    assert cases["found"]["starting_state_reason"] == "lab"
    assert cases["follow"]["materialized_baselines"] == [
        "fresh-host",
        "shell-preconfigured",
    ]
    assert cases["found"]["materialized_baselines"] == [None]


def test_materialization_refuses_a_stored_case_with_no_declaration() -> None:
    with test_database() as conn:
        plan = create_plan(conn, project="yoke", slug="stored-undeclared")
        replace_plan_cases(
            conn,
            plan_id=plan["id"],
            cases=[_machine_case("old", 1, host_baselines=["fresh-host"])],
        )
        # A case stored before declarations existed.
        conn.execute(
            "UPDATE qa_plan_cases SET host_baselines='[]', starting_state=NULL "
            "WHERE plan_id=%s",
            (plan["id"],),
        )
        with pytest.raises(QaPlanError) as refusal:
            plan_cases(conn, plan["id"])
    assert "'stored-undeclared' cannot materialize" in str(refusal.value)
    assert "yoke qa plan edit" in str(refusal.value)


def _add(conn, item_id: int, **start):
    payload = {
        "method_id": "machine-state-check",
        "qa_phase": "verification",
        "instructions": "Check the host.",
        "expected_outcome": "The check passes.",
        "method_config": dict(_ASSERTIONS),
        "workflow_transition_id": item_transition_for_gate(
            conn, item_id=item_id, gate_id=GATE_QA_VERIFICATION
        ),
        **start,
    }
    return qa_requirement_create.handle_qa_requirement_add(
        FunctionCallRequest(
            function="qa.requirement.add",
            actor=ActorContext(actor_id="op", session_id="s-1"),
            target=TargetRef(kind="item", item_id=item_id),
            payload=payload,
        )
    )


@pytest.mark.parametrize(
    ("start", "expected"),
    [
        ({}, "declares no starting state; pass --host-baseline NAME"),
        ({"starting_state": "inherit"}, "belongs to no plan"),
        ({"starting_state": "as_is"}, "without a starting_state_reason"),
        ({"host_baseline": "fresh-hose"}, "available baselines"),
    ],
)
def test_direct_add_refuses_a_machine_case_without_a_usable_start(
    start, expected
) -> None:
    with test_database() as conn:
        insert_item(conn, id=61, title="T", status="implementing")
        conn.commit()
        outcome = _add(conn, 61, **start)
    assert not outcome.primary_success
    assert expected in outcome.error.message


@pytest.mark.parametrize(
    ("start", "stored"),
    [
        ({"host_baseline": "fresh-host"}, ("fresh-host", "baseline", None)),
        (
            {"starting_state": "as_is", "starting_state_reason": "lab host"},
            (None, "as_is", "lab host"),
        ),
    ],
)
def test_direct_add_stores_the_declared_start(start, stored) -> None:
    with test_database() as conn:
        insert_item(conn, id=62, title="T", status="implementing")
        conn.commit()
        outcome = _add(conn, 62, **start)
        assert outcome.primary_success, outcome.error
        row = conn.execute(
            "SELECT host_baseline, starting_state, starting_state_reason "
            "FROM qa_requirements WHERE id=%s",
            (outcome.result_payload["requirement_id"],),
        ).fetchone()
    assert tuple(row) == stored
