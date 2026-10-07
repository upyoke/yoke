"""Whether the execution named by a leased host's owner marker has finished.

Mission preparation finds the host's test-project owner marker on the Test
Machine; only the control plane knows whether that owner is still running.
The caller must own the preparing execution and hold its machine lease, so
the answer is limited to the one host it already leases.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from yoke_contracts.api.function_call import FunctionCallRequest, HandlerOutcome
from yoke_core.domain.handlers.machine_qa import _failure
from yoke_core.domain.handlers.machine_qa_plan_case_request import (
    parse_plan_case_request,
    target_plan_subject,
)
from yoke_core.domain.qa_standalone_execution import require_standalone_project

FUNCTION_ID = "test_machine.mission.owner_state"


class AgentMissionOwnerStateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    execution_id: str = Field(min_length=1)
    owner_execution_id: str = Field(min_length=1)


class AgentMissionOwnerStateResponse(BaseModel):
    execution_id: str
    owner_execution_id: str
    state: str | None
    terminal: bool


def handle_agent_mission_owner_state(request: FunctionCallRequest) -> HandlerOutcome:
    target = target_plan_subject(request, FUNCTION_ID)
    if isinstance(target, HandlerOutcome):
        return target
    item_id, deployment_run_id = target
    parsed = parse_plan_case_request(AgentMissionOwnerStateRequest, request.payload)
    if isinstance(parsed, HandlerOutcome):
        return parsed
    assert isinstance(parsed, AgentMissionOwnerStateRequest)

    from yoke_core.domain.db_helpers import connect, query_one
    from yoke_core.domain.qa_plan_execution_authority import (
        require_plan_execution_owner,
    )
    from yoke_core.domain.qa_plan_execution_schema import (
        TERMINAL_PLAN_EXECUTION_STATES,
    )
    from yoke_core.domain.qa_plan_execution_store import (
        marker,
        select_plan_execution,
    )

    conn = connect()
    try:
        execution = select_plan_execution(conn, parsed.execution_id, lock=False)
        if request.target.kind == "global":
            require_standalone_project(conn, execution, str(request.target.project_id))
        require_plan_execution_owner(
            execution,
            conn=conn,
            item_id=item_id,
            deployment_run_id=deployment_run_id,
            actor_id=request.actor.actor_id,
            session_id=request.actor.session_id,
        )
        if execution.get("machine_lease_id") is None:
            raise ValueError(
                "mission owner state needs the preparing execution's machine "
                "lease; re-run the mission so it acquires the host first"
            )
        row = query_one(
            conn,
            f"SELECT state FROM qa_plan_executions WHERE id={marker(conn)}",
            (parsed.owner_execution_id,),
        )
    except ValueError as exc:
        return _failure("agent_mission_owner_state_failed", str(exc))
    finally:
        conn.close()
    state = str(row["state"]) if row is not None else None
    return HandlerOutcome(
        primary_success=True,
        result_payload={
            "execution_id": parsed.execution_id,
            "owner_execution_id": parsed.owner_execution_id,
            "state": state,
            "terminal": state in TERMINAL_PLAN_EXECUTION_STATES,
        },
    )


def register(registry: Any) -> None:
    registry.register(
        FUNCTION_ID,
        handle_agent_mission_owner_state,
        AgentMissionOwnerStateRequest,
        AgentMissionOwnerStateResponse,
        stability="stable",
        owner_module=__name__,
        target_kinds=["item", "deployment_run", "global"],
        minimum_serving_version="next-release",
        side_effects=[],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=["qa_subject_authority", "actor_session_bound"],
        adapter_status="internal",
        claim_required_kind="qa_subject",
        ambient_session_required=True,
    )


__all__ = [
    "AgentMissionOwnerStateRequest",
    "AgentMissionOwnerStateResponse",
    "handle_agent_mission_owner_state",
    "register",
]
