"""``test_machine.mission.record_connected_machine``: record a walk's connect.

``yoke qa mission connected-machine`` reads the Machine id from the Test
Machine's Yoke config through the mission's lease and calls this function.
Only the execution's own session may call it, and only while the execution
is live. It stores the verified Machine as the docket's ``connected_machine``
(see :mod:`agent_mission_connected_machine`) and returns the launch hint.
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field

from yoke_contracts.api.function_call import FunctionCallRequest, HandlerOutcome

FUNCTION_ID = "test_machine.mission.record_connected_machine"


class MissionConnectedMachineRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    execution_id: str = Field(min_length=1)
    requirement_id: int = Field(ge=1)
    run_id: int = Field(ge=1)
    machine_id: Optional[str] = None


class MissionConnectedMachineResponse(BaseModel):
    execution_id: str
    run_id: int
    machine_id: str
    connected_machine: dict[str, Any]
    launch_hint: str


def _authorize(conn: Any, request: FunctionCallRequest, parsed) -> dict:
    from yoke_core.domain.agent_mission_cleanup import _mission
    from yoke_core.domain.qa_execution_request_identity import resolve_execution_request
    from yoke_core.domain.qa_plan_execution_authority import (
        require_plan_execution_owner,
    )
    from yoke_core.domain.qa_plan_execution_schema import (
        TERMINAL_PLAN_EXECUTION_STATES,
    )
    from yoke_core.domain.qa_plan_execution_store import lock_plan_execution

    execution = lock_plan_execution(conn, parsed.execution_id)
    request = resolve_execution_request(conn, request, execution)
    if request.target.kind == "global":
        from yoke_core.domain.qa_standalone_execution import require_standalone_project

        require_standalone_project(conn, execution, str(request.target.project_id))
    require_plan_execution_owner(
        execution,
        conn=conn,
        item_id=request.target.item_id,
        deployment_run_id=request.target.deployment_run_id,
        actor_id=request.actor.actor_id,
        session_id=request.actor.session_id,
    )
    if execution["state"] in TERMINAL_PLAN_EXECUTION_STATES:
        raise ValueError(
            f"connected_machine_execution_ended: execution {execution['id']} is "
            f"{execution['state']}; walk-end retires its recorded Machine, and "
            "a Machine it never recorded is retired by its owner with "
            "`yoke machine retire MACHINE_ID --confirm`"
        )
    _, _, run_id = _mission(conn, execution, parsed.requirement_id)
    if parsed.run_id != run_id:
        raise ValueError(
            f"connected_machine_run_mismatch: rerun with --run-id {run_id}"
        )
    conn.commit()
    return execution


def handle_record_connected_machine(request: FunctionCallRequest) -> HandlerOutcome:
    from yoke_core.domain.agent_mission_connected_machine import (
        ConnectedMachineRefusal,
        launch_hint,
        record_connected_machine,
    )
    from yoke_core.domain.db_helpers import connect
    from yoke_core.domain.handlers.machine_qa import _failure
    from yoke_core.domain.handlers.machine_qa_plan_case_request import (
        parse_plan_case_request,
        target_plan_subject,
    )
    from yoke_contracts.timestamps import utc_now

    target = target_plan_subject(request, FUNCTION_ID)
    if isinstance(target, HandlerOutcome):
        return target
    parsed = parse_plan_case_request(MissionConnectedMachineRequest, request.payload)
    if isinstance(parsed, HandlerOutcome):
        return parsed
    conn = connect()
    try:
        execution = _authorize(conn, request, parsed)
        entry = record_connected_machine(
            conn, run_id=parsed.run_id, machine_id=parsed.machine_id, now=utc_now()
        )
    except ConnectedMachineRefusal as exc:
        conn.rollback()
        return _failure(exc.code, str(exc))
    except (LookupError, ValueError) as exc:
        conn.rollback()
        return _failure(
            "connected_machine_record_failed",
            f"{exc}; rerun connected-machine after resolving the named blocker",
        )
    finally:
        conn.close()
    response = MissionConnectedMachineResponse(
        execution_id=str(execution["id"]),
        run_id=parsed.run_id,
        machine_id=entry["machine_id"],
        connected_machine=entry,
        launch_hint=launch_hint(entry["machine_id"]),
    )
    return HandlerOutcome(primary_success=True, result_payload=response.model_dump())


def register(registry: Any) -> None:
    registry.register(
        FUNCTION_ID,
        handle_record_connected_machine,
        MissionConnectedMachineRequest,
        MissionConnectedMachineResponse,
        stability="stable",
        owner_module=__name__,
        target_kinds=["item", "global"],
        minimum_serving_version="next-release",
        side_effects=["qa_run_write"],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=["qa_subject_authority", "actor_session_bound"],
        adapter_status="internal",
        claim_required_kind="qa_subject",
        ambient_session_required=True,
    )


__all__ = [
    "FUNCTION_ID",
    "MissionConnectedMachineRequest",
    "MissionConnectedMachineResponse",
    "handle_record_connected_machine",
    "register",
]
