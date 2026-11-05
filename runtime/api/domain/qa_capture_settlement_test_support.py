# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

from typing import Any

from runtime.api.domain.machine_qa_host_test_support import (
    configure_test_machine,
)

from runtime.api.domain.machine_qa_test_support import FakeHostControl

from runtime.api.fixtures.backlog_inserts import insert_item

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)

from yoke_core.domain.handlers.machine_qa_plan_case import handle_plan_case_begin

from yoke_core.domain.agent_mission_recording import handle_agent_mission_ready

from yoke_core.domain.host_control_runner import (
    clear_host_control_factory,
    register_host_control_factory,
)

from yoke_core.domain.machine_qa_local_execution import (
    prepare_agent_mission_contract,
)

from yoke_core.domain.qa_catalog_schema import seed_builtin_qa_methods

from yoke_core.domain.qa_plan_attachments import (
    attach_plan_to_item,
    materialize_for_item,
)

from yoke_core.domain.qa_plan_execution_lifecycle import finish_plan_execution

from yoke_core.domain.qa_plan_execution_state import (
    begin_plan_execution,
    lock_plan_execution,
)

from yoke_core.domain.qa_plan_management import create_plan, replace_plan_cases

from yoke_core.domain.qa_plan_review import begin_plan_review

from yoke_core.domain.qa_plan_review_submission import submit_plan_review

from yoke_core.domain.qa_terminal_settlement import find_unsettled_records

from yoke_core.domain.schema_init_tables import create_governed_tables

ACTOR = ActorContext(actor_id="1", session_id="settlement-session")


def _request(
    function: str,
    *,
    item_id: int,
    execution_id: str,
    requirement_id: int,
    ordinal: int | None = None,
    payload: dict[str, Any] | None = None,
) -> FunctionCallRequest:
    return FunctionCallRequest(
        function=function,
        actor=ACTOR,
        target=TargetRef(kind="item", item_id=item_id),
        payload={
            "execution_id": execution_id,
            "requirement_id": requirement_id,
            **({"ordinal": ordinal} if ordinal is not None else {}),
            **(payload or {}),
        },
    )


def _materialize_mission(conn: Any, *, item_id: int) -> int:
    """One materialized exploratory-mission requirement; returns its id."""
    create_governed_tables(conn)
    seed_builtin_qa_methods(conn)
    plan = create_plan(
        conn,
        project="yoke",
        slug=f"mission-settlement-{item_id}",
        name="Mission settlement",
    )
    replace_plan_cases(
        conn,
        plan_id=int(plan["id"]),
        cases=[
            {
                "case_key": "explore-onboarding",
                "position": 1,
                "method_id": "exploratory-mission",
                "instructions": "Investigate onboarding gaps.",
                "expected_outcome": "Return ranked findings.",
                "method_config": {"executor": "informed_subagent", "os": "macos"},
                "host_baselines": ["fresh-host"],
            }
        ],
    )
    insert_item(
        conn,
        id=item_id,
        title="Explore new-user installation",
        workflow_id="issue",
        status="implementing",
    )
    attach_plan_to_item(
        conn,
        plan_id=int(plan["id"]),
        item_id=item_id,
        transition_id="reviewing-implementation",
    )
    materialized = materialize_for_item(
        conn,
        item_id=item_id,
        transition_id="reviewing-implementation",
    )
    return int(materialized["created_requirement_ids"][0])


def _capture_attempt(
    test_db: Any,
    *,
    item_id: int,
    requirement_id: int,
) -> str:
    """Begin an execution and land its docket capture; returns execution id."""
    execution = begin_plan_execution(
        test_db,
        item_id=item_id,
        transition_id="reviewing-implementation",
        actor_id=ACTOR.actor_id,
        session_id=ACTOR.session_id,
    )
    execution_id = str(execution["id"])
    begun = handle_plan_case_begin(
        _request(
            "test_machine.plan_case.begin",
            item_id=item_id,
            execution_id=execution_id,
            ordinal=0,
            requirement_id=requirement_id,
        )
    )
    assert begun.primary_success, begun.error
    contract = begun.result_payload["execution"]
    register_host_control_factory(lambda _material: FakeHostControl())
    try:
        prepared = prepare_agent_mission_contract(contract)
    finally:
        clear_host_control_factory()
    ready = handle_agent_mission_ready(
        _request(
            "test_machine.mission.ready",
            item_id=item_id,
            execution_id=execution_id,
            ordinal=0,
            requirement_id=requirement_id,
            payload=prepared,
        )
    )
    assert ready.primary_success, ready.error
    return execution_id


def _unsettled_run_ids(conn: Any, requirement_id: int) -> list[int]:
    return [
        int(row["id"])
        for row in conn.execute(
            "SELECT id FROM qa_runs WHERE qa_requirement_id=%s "
            "AND verdict IS NULL ORDER BY id",
            (requirement_id,),
        ).fetchall()
    ]


def _submit_pass(
    conn: Any,
    execution: Any,
    bundle: Any,
    requirement_id: int,
    rationale: str,
) -> dict[str, Any]:
    return submit_plan_review(
        conn,
        execution,
        bundle_id=bundle["bundle_id"],
        bundle_digest=bundle["bundle_digest"],
        verdicts=[
            {
                "requirement_id": requirement_id,
                "verdict": "pass",
                "rationale": rationale,
            }
        ],
        reviewer_actor_id=ACTOR.actor_id,
        reviewer_session_id=ACTOR.session_id,
    )
