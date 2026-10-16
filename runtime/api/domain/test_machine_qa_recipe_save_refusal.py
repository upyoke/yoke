"""A Terminal case missing its recipe fields is refused before any host work.

Plan authoring, standalone requirement add and materialization each run the
runner's own recipe contract, and the local runner checks it again before the
starting-state reset, so a case that could never run costs no host reset.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from runtime.api.domain.machine_qa_fixture_lifecycle_test_support import (
    case_contract,
)
from runtime.api.domain.machine_qa_host_test_support import _terminal_recipe
from runtime.api.domain.qa_plan_execution_test_support import TEST_ITEM_ID
from runtime.api.fixtures.backlog_inserts import insert_item
from runtime.api.fixtures.pg_testdb import test_database
from yoke_contracts.machine_qa_failures import HostControlLocalError
from yoke_core.domain import machine_qa_local_execution as local
from yoke_core.domain.handlers.qa_requirement_method_validation import (
    validate_method_requirement,
)
from yoke_core.domain.qa_plan_attachments import (
    materialize_for_item,
    set_project_default,
)
from yoke_core.domain.qa_plan_management import (
    QaPlanError,
    create_plan,
    replace_plan_cases,
)


def _terminal_case(**fields) -> dict:
    return {
        "case_key": "hosted-connect",
        "position": 1,
        "method_id": "terminal-check",
        "instructions": "Connect the machine to the hosted service.",
        "expected_outcome": "Setup reaches the GitHub question.",
        "method_config": _terminal_recipe(),
        "host_baselines": ["fresh-host"],
        **fields,
    }


def test_authoring_refuses_a_terminal_case_missing_both_recipe_fields() -> None:
    with test_database() as conn:
        plan = create_plan(conn, project="yoke", slug="connect", name="Connect")
        with pytest.raises(QaPlanError) as refused:
            replace_plan_cases(conn, plan_id=plan["id"], cases=[_terminal_case()])
    message = str(refused.value)
    assert "case 'hosted-connect'" in message
    assert "terminal_case_fields_missing" in message
    assert "missing=['entry_surface', 'required_completion']" in message
    assert "yoke qa plan edit PLAN_SLUG" in message


def test_authoring_refuses_a_terminal_case_missing_only_required_completion() -> None:
    with test_database() as conn:
        plan = create_plan(conn, project="yoke", slug="connect", name="Connect")
        with pytest.raises(QaPlanError, match=r"missing=\['required_completion'\]"):
            replace_plan_cases(
                conn,
                plan_id=plan["id"],
                cases=[_terminal_case(entry_surface="printf done")],
            )


def test_materialization_refuses_a_stored_case_missing_its_entry_surface() -> None:
    with test_database() as conn:
        insert_item(conn, id=TEST_ITEM_ID, title="Run QA", workflow_id="issue")
        plan = create_plan(conn, project="yoke", slug="connect", name="Connect")
        replace_plan_cases(
            conn,
            plan_id=plan["id"],
            cases=[
                _terminal_case(
                    entry_surface="printf done", required_completion="complete"
                )
            ],
        )
        conn.execute(
            "UPDATE qa_plan_cases SET entry_surface=NULL WHERE plan_id=%s",
            (int(plan["id"]),),
        )
        set_project_default(
            conn,
            plan_id=plan["id"],
            workflow_id="issue",
            transition_id="implemented",
        )
        with pytest.raises(QaPlanError, match=r"missing=\['entry_surface'\]"):
            materialize_for_item(
                conn, item_id=TEST_ITEM_ID, transition_id="implemented"
            )


def test_requirement_add_refuses_a_terminal_case_it_cannot_give_an_entry() -> None:
    with test_database() as conn:
        refused = validate_method_requirement(
            conn,
            {
                "method_id": "terminal-check",
                "instructions": "Run the recipe.",
                "expected_outcome": "It completes.",
                "method_config": _terminal_recipe(),
                "host_baseline": "fresh-host",
            },
            "$.payload",
        )
    assert refused is not None
    assert "terminal_case_fields_missing" in str(refused)


def test_local_runner_refuses_a_bad_case_before_touching_the_host(
    monkeypatch,
) -> None:
    case = case_contract(host_baseline="fresh-host").model_copy(
        update={"entry_surface": None, "required_completion": None}
    )
    contract = SimpleNamespace(
        operation="plan_case", baselines=["fresh-host"], cases=[case]
    )
    touched: list[str] = []
    monkeypatch.setattr(
        local.HostControlExecutionContract, "model_validate", lambda raw: contract
    )
    monkeypatch.setattr(
        local, "_execution", lambda *args, **kwargs: touched.append("host")
    )
    with pytest.raises(HostControlLocalError) as refused:
        local.execute_machine_case_contract({"contract": "issued"})
    assert touched == []
    assert refused.value.code == "machine_qa_recipe_invalid"
    assert refused.value.phase == "recipe_validation"
    assert "entry_surface" in str(refused.value)
    assert "yoke qa plan rematerialize" in refused.value.recovery_hint
