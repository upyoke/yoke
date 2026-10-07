"""Case-declared Test Machine constraints remain durable and enforceable."""

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
    MachineConstraintError,
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


def _machine_case(machine: str) -> dict[str, Any]:
    return {
        "case_key": "machine-generation-check",
        "position": 1,
        "method_id": "machine-state-check",
        "instructions": "Check behavior that depends on this machine generation.",
        "expected_outcome": "The machine-specific behavior passes.",
        "method_config": {
            "machine": machine,
            "assertions": [{"argv": ["/usr/bin/true"]}],
        },
    }


@pytest.mark.parametrize("specific_capability_snapshot", [True, False])
def test_execution_honors_case_machine_with_or_without_specific_capability_snapshot(
    test_db: Any,
    tmp_path: Path,
    monkeypatch: Any,
    specific_capability_snapshot: bool,
) -> None:
    configure_test_machine(test_db, tmp_path, monkeypatch)
    plan = create_plan(
        test_db,
        project="yoke",
        slug="machine-generation-check",
    )
    replace_plan_cases(
        test_db,
        plan_id=int(plan["id"]),
        cases=[_machine_case("mac-mini-lab")],
    )
    item_id = 4470
    insert_item(
        test_db,
        id=item_id,
        title="Run a machine-specific check",
        workflow_id="issue",
        status="implementing",
    )
    attach_plan_to_item(
        test_db,
        plan_id=int(plan["id"]),
        item_id=item_id,
        transition_id="reviewing-implementation",
    )
    materialized = materialize_for_item(
        test_db,
        item_id=item_id,
        transition_id="reviewing-implementation",
    )
    requirement_id = materialized["created_requirement_ids"][0]
    stored = test_db.execute(
        "SELECT capability_requirements,method_config FROM qa_requirements WHERE id=%s",
        (requirement_id,),
    ).fetchone()

    assert json.loads(stored["capability_requirements"]) == [
        "test-machine",
        "test-machine:mac-mini-lab",
    ]
    assert json.loads(stored["method_config"])["machine"] == "mac-mini-lab"
    if not specific_capability_snapshot:
        # Direct requirements retain the pin in method_config without adding
        # a machine-specific capability token, including admitted copies.
        test_db.execute(
            "UPDATE qa_requirements SET capability_requirements=%s,"
            "plan_id=NULL,plan_case_key=NULL WHERE id=%s",
            (json.dumps(["test-machine"]), requirement_id),
        )
        test_db.commit()
    context = get_case_execution_context(
        test_db,
        requirement_id=requirement_id,
        host_capability_kinds=["test-machine"],
    )
    assert resolve_case_machine(context, None) == "mac-mini-lab"
    assert resolve_plan_machine([context], None) == "mac-mini-lab"
    with pytest.raises(MachineConstraintError, match=MACHINE_CONSTRAINT_MISMATCH):
        begin_plan_execution(
            test_db,
            item_id=item_id,
            transition_id="reviewing-implementation",
            machine="mac-studio-lab",
            actor_id="2",
            session_id="session-machine-constraint",
        )
    assert test_db.execute("SELECT COUNT(*) FROM qa_plan_executions").fetchone()[0] == 0


def test_plan_run_refuses_an_unregistered_machine_pin(
    test_db: Any,
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    configure_test_machine(test_db, tmp_path, monkeypatch)
    plan = create_plan(test_db, project="yoke", slug="unpinned-machine-check")
    case = _machine_case("mac-mini-lab")
    case["method_config"].pop("machine")
    replace_plan_cases(test_db, plan_id=int(plan["id"]), cases=[case])
    item_id = 4471
    insert_item(
        test_db,
        id=item_id,
        title="Run an unpinned machine check",
        workflow_id="issue",
        status="implementing",
    )
    attach_plan_to_item(
        test_db,
        plan_id=int(plan["id"]),
        item_id=item_id,
        transition_id="reviewing-implementation",
    )
    materialize_for_item(
        test_db,
        item_id=item_id,
        transition_id="reviewing-implementation",
    )

    with pytest.raises(MachineConstraintError, match="run pin requires unregistered"):
        begin_plan_execution(
            test_db,
            item_id=item_id,
            transition_id="reviewing-implementation",
            machine="mac-pro-missing",
            actor_id="2",
            session_id="session-missing-machine",
        )
    assert test_db.execute("SELECT COUNT(*) FROM qa_plan_executions").fetchone()[0] == 0


def test_plan_authoring_refuses_an_unregistered_case_machine(test_db: Any) -> None:
    plan = create_plan(
        test_db,
        project="yoke",
        slug="missing-machine-check",
    )
    with pytest.raises(QaPlanError, match="unregistered test machine"):
        replace_plan_cases(
            test_db,
            plan_id=int(plan["id"]),
            cases=[_machine_case("mac-pro-missing")],
        )


def test_run_pin_must_satisfy_case_and_roster_constraints() -> None:
    case = {
        "case_key": "generation-check",
        "required_capability_kinds": ["test-machine:mac-mini-lab"],
    }
    assert resolve_case_machine(case, None) == "mac-mini-lab"
    with pytest.raises(MachineConstraintError, match=MACHINE_CONSTRAINT_MISMATCH):
        resolve_case_machine(case, "mac-studio-lab")
    with pytest.raises(
        MachineConstraintError,
        match="test_machine_plan_constraints_conflict",
    ):
        resolve_plan_machine(
            [
                case,
                {
                    "case_key": "newer-generation-check",
                    "required_capability_kinds": ["test-machine:mac-studio-lab"],
                },
            ],
            None,
        )


def test_configured_machine_conflicts_are_refused_without_a_run_pin() -> None:
    case = {
        "case_key": "configured-host-check",
        "required_capability_kinds": ["test-machine"],
        "method_config": {"machine": "linux-lab"},
    }
    assert resolve_case_machine(case, None) == "linux-lab"
    with pytest.raises(MachineConstraintError, match=MACHINE_CONSTRAINT_MISMATCH):
        resolve_plan_machine([case], "windows-lab")
    with pytest.raises(MachineConstraintError, match="multiple specific Test Machines"):
        resolve_case_machine(
            {**case, "required_capability_kinds": ["test-machine:windows-lab"]},
            None,
        )
    with pytest.raises(
        MachineConstraintError, match="test_machine_plan_constraints_conflict"
    ):
        resolve_plan_machine(
            [case, {"method_config": {"machine": "windows-lab"}}], None
        )
