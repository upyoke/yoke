# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

import subprocess

from typing import Any

from runtime.api.domain.machine_qa_host_test_support import configure_test_machine

from runtime.api.domain.machine_qa_test_support import FakeHostControl

from runtime.api.fixtures.backlog_inserts import insert_item

from runtime.api.domain import qa_execution_walk_states_test_support as walk_states

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)

from yoke_contracts.machine_qa_execution import (
    AGENT_MISSION_ARTIFACT_LIMIT,
)

from yoke_contracts.machine_qa_terminal_bridge import (
    TERMINAL_SCREEN_RECORDING_REQUIRED_ERROR_CODE,
)

from yoke_contracts.qa_mission_scratch import mission_scratch_path

from yoke_core.domain.agent_mission_recording import (
    handle_agent_mission_access,
    handle_agent_mission_ready,
)

from yoke_core.domain.agent_mission_review import agent_mission_dispatch_contract

from yoke_core.domain.coordination_claims import get_claim

from yoke_core.domain.handlers.machine_qa_plan_case import handle_plan_case_begin

from yoke_core.domain.host_control_runner import (
    clear_host_control_factory,
    register_host_control_factory,
)

from yoke_core.domain.machine_qa_local_execution import (
    execute_agent_mission_host_command,
    prepare_agent_mission_contract,
)

from yoke_core.domain.qa_catalog_schema import seed_builtin_qa_methods

from yoke_core.domain.qa_plan_attachments import (
    attach_plan_to_item,
    materialize_for_item,
)

from yoke_core.domain.qa_plan_execution_state import (
    begin_plan_execution,
    lock_plan_execution,
)

from yoke_core.domain.qa_plan_management import create_plan, replace_plan_cases

from yoke_core.domain.qa_plan_review import begin_plan_review

from yoke_core.domain.qa_plan_review_submission import submit_plan_review

from yoke_core.domain.schema_init_tables import create_governed_tables

ACTOR = ActorContext(actor_id="1", session_id="session-agent-mission")


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
    create_governed_tables(conn)
    seed_builtin_qa_methods(conn)
    plan = create_plan(
        conn,
        project="yoke",
        slug=f"exploratory-mission-{item_id}",
        name="Exploratory mission",
    )
    replace_plan_cases(
        conn,
        plan_id=int(plan["id"]),
        cases=[
            {
                "case_key": "new-user-install",
                "position": 1,
                "method_id": "exploratory-mission",
                "instructions": (
                    "Install as a new user and investigate onboarding gaps "
                    "using the terminal, browser, and visible desktop."
                ),
                "expected_outcome": (
                    "Return ranked actionable findings and name anything "
                    "that could not be checked."
                ),
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
