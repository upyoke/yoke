"""QA cases select Test Machines by OS and tags; only a run pin names a host."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from runtime.api.domain.machine_qa_host_test_support import (
    configure_test_machine,
)
from runtime.api.fixtures.backlog_inserts import insert_item
from yoke_core.domain.machine_qa_case_machine import (
    MACHINE_CONSTRAINT_MISMATCH,
    TEST_MACHINE_NAME_FORBIDDEN,
    MachineConstraintError,
    refuse_stored_host_names,
    resolve_case_machine,
    resolve_plan_machine,
)
from yoke_core.domain.qa_case_execution_context import get_case_execution_context
from yoke_core.domain.qa_plan_attachments import (
    attach_plan_to_item,
    materialize_for_item,
)
from yoke_core.domain.qa_plan_management import (
    QaPlanError,
    create_plan,
    replace_plan_cases,
)
from yoke_core.domain.qa_plan_execution_state import begin_plan_execution


def _machine_case(**config: Any) -> dict[str, Any]:
    return {
        "case_key": "machine-generation-check",
        "position": 1,
        "method_id": "machine-state-check",
        "instructions": "Check behavior on any macOS Test Machine.",
        "expected_outcome": "The macOS behavior passes.",
        "method_config": {
            "os": "macos",
            "assertions": [{"argv": ["/usr/bin/true"]}],
            **config,
        },
        "host_baselines": ["fresh-host"],
    }


def _materialized(test_db: Any, *, slug: str, item_id: int, case: dict) -> int:
    plan = create_plan(test_db, project="yoke", slug=slug)
    replace_plan_cases(test_db, plan_id=int(plan["id"]), cases=[case])
    insert_item(
        test_db, id=item_id, title=slug, workflow_id="issue", status="implementing"
    )
    attach_plan_to_item(
        test_db,
        plan_id=int(plan["id"]),
        item_id=item_id,
        transition_id="reviewing-implementation",
    )
    materialized = materialize_for_item(
        test_db, item_id=item_id, transition_id="reviewing-implementation"
    )
    return int(materialized["created_requirement_ids"][0])


def test_os_case_materializes_without_any_host_name(
    test_db: Any, tmp_path: Path, monkeypatch: Any
) -> None:
    configure_test_machine(test_db, tmp_path, monkeypatch)
    requirement_id = _materialized(
        test_db, slug="macos-check", item_id=4470, case=_machine_case()
    )
    stored = test_db.execute(
        "SELECT capability_requirements,method_config FROM qa_requirements WHERE id=%s",
        (requirement_id,),
    ).fetchone()
    assert json.loads(stored["capability_requirements"]) == ["test-machine"]
    assert json.loads(stored["method_config"])["os"] == "macos"
    context = get_case_execution_context(
        test_db, requirement_id=requirement_id, host_capability_kinds=["test-machine"]
    )
    assert (context["starting_state"], context["starting_state_reason"]) == (
        "baseline",
        None,
    )
    assert resolve_case_machine(context, None) is None
    assert resolve_case_machine(context, "mac-mini-lab") == "mac-mini-lab"


@pytest.mark.parametrize(
    "config",
    [
        {"test_machine": "mac-mini-lab"},
        {"test_machine_reason": "this generation"},
        {"os": None, "test_machines": ["mac-mini-lab", "linux-lab"]},
    ],
)
def test_plan_authoring_refuses_a_named_host(test_db: Any, config: dict) -> None:
    plan = create_plan(test_db, project="yoke", slug="named-host-check")
    case = _machine_case(**config)
    if case["method_config"].get("os") is None:
        case["method_config"].pop("os")
    with pytest.raises(QaPlanError, match=TEST_MACHINE_NAME_FORBIDDEN) as refused:
        replace_plan_cases(test_db, plan_id=int(plan["id"]), cases=[case])
    assert '[{"os":"linux"},{"os":"macos","driver":true}]' in str(refused.value)


def test_plan_authoring_refuses_a_specific_machine_capability(test_db: Any) -> None:
    plan = create_plan(test_db, project="yoke", slug="named-kind-check")
    case = {**_machine_case(), "required_capability_kinds": ["test-machine:mac-mini-lab"]}
    with pytest.raises(QaPlanError, match=TEST_MACHINE_NAME_FORBIDDEN):
        replace_plan_cases(test_db, plan_id=int(plan["id"]), cases=[case])


def test_plan_run_pin_must_match_the_case_os(
    test_db: Any, tmp_path: Path, monkeypatch: Any
) -> None:
    configure_test_machine(test_db, tmp_path, monkeypatch)
    case = _machine_case()
    case["method_config"]["os"] = "linux"
    case["method_config"]["assertions"] = [{"argv": ["/usr/bin/stat", "-c", "%a"]}]
    _materialized(test_db, slug="linux-check", item_id=4472, case=case)
    with pytest.raises(MachineConstraintError, match=MACHINE_CONSTRAINT_MISMATCH) as refused:
        begin_plan_execution(
            test_db,
            item_id=4472,
            transition_id="reviewing-implementation",
            test_machine="mac-mini-lab",
            actor_id="2",
            session_id="session-machine-constraint",
        )
    assert "linux" in str(refused.value)
    assert test_db.execute("SELECT COUNT(*) FROM qa_plan_executions").fetchone()[0] == 0


def test_plan_run_refuses_an_unregistered_machine_pin(
    test_db: Any, tmp_path: Path, monkeypatch: Any
) -> None:
    configure_test_machine(test_db, tmp_path, monkeypatch)
    _materialized(test_db, slug="unpinned-machine-check", item_id=4471, case=_machine_case())
    with pytest.raises(MachineConstraintError, match="run pin requires unregistered"):
        begin_plan_execution(
            test_db,
            item_id=4471,
            transition_id="reviewing-implementation",
            test_machine="mac-pro-missing",
            actor_id="2",
            session_id="session-missing-machine",
        )
    assert test_db.execute("SELECT COUNT(*) FROM qa_plan_executions").fetchone()[0] == 0


def test_plan_begin_refuses_a_stored_host_name(
    test_db: Any, tmp_path: Path, monkeypatch: Any
) -> None:
    configure_test_machine(test_db, tmp_path, monkeypatch)
    requirement_id = _materialized(
        test_db, slug="stored-pin-check", item_id=4473, case=_machine_case()
    )
    config = {"test_machine": "mac-mini-lab", "assertions": [{"argv": ["/usr/bin/true"]}]}
    test_db.execute(
        # A row seeded past migration 0119, detached from its plan's currency.
        "UPDATE qa_requirements SET method_config=%s,plan_id=NULL,plan_case_key=NULL "
        "WHERE id=%s",
        (json.dumps(config), requirement_id),
    )
    test_db.commit()
    with pytest.raises(MachineConstraintError, match=TEST_MACHINE_NAME_FORBIDDEN) as refused:
        begin_plan_execution(
            test_db,
            item_id=4473,
            transition_id="reviewing-implementation",
            test_machine=None,
            actor_id="2",
            session_id="session-stored-pin",
        )
    assert "yoke qa plan-cases replace" in str(refused.value)


@pytest.mark.parametrize(
    "case",
    [
        {"method_config": {"test_machine": "linux-lab"}},
        {"method_config": json.dumps({"test_machine_reason": "x"})},
        {"method_config": {"test_machines": ["linux-lab", "mac-lab"]}},
        {"capability_requirements": json.dumps(["test-machine:linux-lab"])},
    ],
)
def test_stored_host_names_are_refused(case: dict) -> None:
    with pytest.raises(MachineConstraintError, match=TEST_MACHINE_NAME_FORBIDDEN):
        refuse_stored_host_names(case)


def test_unpinned_plan_needs_no_host_check(test_db: Any) -> None:
    assert resolve_plan_machine(test_db, [{"method_config": {"os": "linux"}}], None) is None
