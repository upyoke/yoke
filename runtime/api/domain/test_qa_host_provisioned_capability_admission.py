"""Admission for substrate Yoke installs on the machine that runs the case."""

from __future__ import annotations

import json
from typing import Any

import pytest

from runtime.api.fixtures.backlog_inserts import insert_item
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_contracts.machine_config.test_machine import (
    test_machine_capability_type as _machine_capability_type,
)
from yoke_core.domain.handlers.qa_case_execution import (
    handle_case_execution_begin,
)
from yoke_core.domain.qa_case_execution_context import (
    QaCaseExecutionError,
    get_case_execution_context,
)
from yoke_core.domain.qa_method_capabilities import (
    RUNNER_HOST_PROVISIONED_CAPABILITY_KINDS,
    host_provisioned_capability_kinds,
)
from yoke_core.domain.qa_method_management import register_project_method


class _KeepOpen:
    """Hand the handler this test's connection without ending its transaction."""

    def __init__(self, conn: Any) -> None:
        self._conn = conn

    def __enter__(self) -> Any:
        return self._conn

    def __exit__(self, *_exc: Any) -> bool:
        return False


def _requirement(
    conn: Any,
    *,
    item_id: int,
    required: list[str],
    method_id: str = "browser-check",
    method_name: str = "Browser check",
    runner_id: str = "browser_substrate",
    verdict_path: str = "automatic",
) -> int:
    """Insert one ad-hoc case the shared runner can be handed."""
    row = conn.execute(
        "INSERT INTO qa_requirements("
        "item_id,qa_kind,qa_phase,blocking_mode,requirement_source,"
        "capability_requirements,method_id,method_name,runner_id,"
        "verdict_path,instructions,expected_outcome,method_config,created_at"
        ") VALUES(%s,'plan_case','verification','blocking','flow_derived',"
        "%s,%s,%s,%s,%s,"
        "'Open the dashboard.','The dashboard renders.',"
        "'{\"base_url\": \"http://localhost:3000\"}',%s) RETURNING id",
        (
            int(item_id),
            json.dumps(required),
            method_id,
            method_name,
            runner_id,
            verdict_path,
            "2026-09-15T12:00:00Z",
        ),
    ).fetchone()
    return int(row["id"])


def test_host_provisioning_is_a_runner_property_not_a_kind_property() -> None:
    declared = ["browser-control", "desktop-control", "test-machine"]

    # Runners that install the browser where the case executes.
    assert host_provisioned_capability_kinds("browser_substrate", declared) == (
        "browser-control",
    )
    assert host_provisioned_capability_kinds("agent_mission", declared) == (
        "browser-control",
    )

    # Runners that install nothing keep every gate they had.
    for runner in ("worktree_run", "ci_run", "host_control", ""):
        assert host_provisioned_capability_kinds(runner, declared) == ()

    # Project/host authority is never provisioned by any runner.
    for kinds in RUNNER_HOST_PROVISIONED_CAPABILITY_KINDS.values():
        assert "test-machine" not in kinds
        assert "desktop-control" not in kinds


def test_first_browser_case_admits_without_a_project_capability_row(
    test_db: Any,
) -> None:
    """Installed browser tooling runs without an otherwise empty project row."""
    item = insert_item(test_db, id=2610, project_sequence=2610)
    requirement_id = _requirement(
        test_db, item_id=int(item["id"]), required=["browser-control"]
    )

    # No project_capabilities row, and no shipped harness manifest publishes
    # host_capability_kinds — this is exactly a first-use machine.
    context = get_case_execution_context(
        test_db,
        requirement_id=requirement_id,
        host_capability_kinds=[],
    )

    assert context["requirement_id"] == requirement_id
    assert context["runner_id"] == "browser_substrate"
    assert context["required_capability_kinds"] == ["browser-control"]


def test_admission_refuses_a_capability_the_host_cannot_provision(
    test_db: Any,
) -> None:
    item = insert_item(test_db, id=2611, project_sequence=2611)
    requirement_id = _requirement(
        test_db,
        item_id=int(item["id"]),
        required=["browser-control", "desktop-control"],
    )

    with pytest.raises(QaCaseExecutionError) as refusal:
        get_case_execution_context(
            test_db,
            requirement_id=requirement_id,
            host_capability_kinds=[],
        )

    message = str(refusal.value)
    assert "desktop-control" in message
    assert "browser-control" not in message


def test_admission_still_routes_test_machine_capabilities(test_db: Any) -> None:
    """Test-machine routing stays a project-authority fact admission enforces."""
    item = insert_item(test_db, id=2612, project_sequence=2612)
    requirement_id = _requirement(
        test_db,
        item_id=int(item["id"]),
        required=["browser-control", "test-machine"],
    )

    with pytest.raises(QaCaseExecutionError) as refusal:
        get_case_execution_context(
            test_db,
            requirement_id=requirement_id,
            host_capability_kinds=[],
        )
    assert "test-machine" in str(refusal.value)


def test_command_case_declaring_browser_control_is_still_refused(
    test_db: Any,
) -> None:
    """A runner that installs nothing keeps the gate it always had."""
    item = insert_item(test_db, id=2615, project_sequence=2615)
    requirement_id = _requirement(
        test_db,
        item_id=int(item["id"]),
        required=["browser-control"],
        method_id="command",
        method_name="Command",
        runner_id="worktree_run",
    )

    with pytest.raises(QaCaseExecutionError) as refusal:
        get_case_execution_context(
            test_db,
            requirement_id=requirement_id,
            host_capability_kinds=[],
        )
    assert "browser-control" in str(refusal.value)


def test_public_case_execution_begin_admits_a_first_use_browser_case(
    test_db: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The public function-call boundary admits it, not just the reader."""
    item = insert_item(test_db, id=2616, project_sequence=2616)
    requirement_id = _requirement(
        test_db, item_id=int(item["id"]), required=["browser-control"]
    )
    test_db.commit()

    monkeypatch.setattr(
        "yoke_core.domain.db_helpers.connect",
        lambda *a, **k: _KeepOpen(test_db),
    )
    monkeypatch.setattr(
        "yoke_core.domain.qa_start_bound_authority.resolve_start_bound_claim_id",
        lambda *a, **k: None,
    )

    outcome = handle_case_execution_begin(
        FunctionCallRequest(
            function="qa.case_execution.begin",
            actor=ActorContext(actor_id="2", session_id="session-first-use"),
            target=TargetRef(kind="qa_requirement", qa_requirement_id=requirement_id),
            payload={},
        )
    )

    assert outcome.primary_success, outcome.error
    assert outcome.result_payload["case"]["runner_id"] == "browser_substrate"


def test_project_authored_browser_method_admits_without_a_project_row(
    test_db: Any,
) -> None:
    """A project's own browser method reaches its runner on first use too."""
    method = register_project_method(
        test_db,
        project="yoke",
        slug="checkout-smoke",
        name="Checkout smoke",
        description="Assert the checkout route renders.",
        runner_id="browser_substrate",
        verdict_path="automatic",
        verdict_contract="assertions",
        evidence_contract="assertions",
        required_capability_kinds=["browser-control"],
    )
    item = insert_item(test_db, id=2617, project_sequence=2617)
    requirement_id = _requirement(
        test_db,
        item_id=int(item["id"]),
        required=["browser-control"],
        method_id=str(method["id"]),
        method_name="Checkout smoke",
    )

    context = get_case_execution_context(
        test_db,
        requirement_id=requirement_id,
        host_capability_kinds=[],
    )
    assert context["method_id"] == str(method["id"])
    assert context["required_capability_kinds"] == ["browser-control"]


def test_mission_needs_its_test_machine_but_no_browser_row(
    test_db: Any,
) -> None:
    """A remote execution host stays a project registration; its browser does not."""
    item = insert_item(test_db, id=2618, project_sequence=2618)
    requirement_id = _requirement(
        test_db,
        item_id=int(item["id"]),
        required=["browser-control", "test-machine"],
        method_id="exploratory-mission",
        method_name="Exploratory mission",
        runner_id="agent_mission",
        verdict_path="agent",
    )

    with pytest.raises(QaCaseExecutionError) as refusal:
        get_case_execution_context(
            test_db,
            requirement_id=requirement_id,
            host_capability_kinds=[],
        )
    message = str(refusal.value)
    assert "test-machine" in message
    assert "browser-control" not in message

    test_db.execute(
        "INSERT INTO project_capabilities(project_id,type) VALUES(1,%s)",
        (_machine_capability_type("mac-mini-lab"),),
    )
    context = get_case_execution_context(
        test_db,
        requirement_id=requirement_id,
        host_capability_kinds=[],
    )
    assert context["runner_id"] == "agent_mission"
