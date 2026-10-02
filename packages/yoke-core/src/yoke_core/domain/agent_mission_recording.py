"""Durable mission docket creation and leased walker access."""

from __future__ import annotations

from typing import Any

from yoke_contracts.api.function_call import FunctionCallRequest, HandlerOutcome
from yoke_core.domain.agent_mission_docket import insert_mission_docket
from yoke_core.domain.handlers.machine_qa import _failure
from yoke_core.domain.handlers.machine_qa_plan_case import (
    _assert_current_snapshot,
    _owned_case,
)
from yoke_core.domain.handlers.machine_qa_plan_case_models import (
    AgentMissionAccessRequest,
    AgentMissionAccessResponse,
    AgentMissionPlanCaseReadyRequest,
    AgentMissionPlanCaseReadyResponse,
)
from yoke_core.domain.handlers.machine_qa_plan_case_request import (
    parse_plan_case_request,
    target_plan_subject,
)
from yoke_core.domain.machine_qa_plan_protocol import plan_case_contract_arguments
from yoke_core.domain.qa_standalone_execution import require_standalone_project


def _recorded_result(
    conn: Any,
    *,
    execution_id: str,
    ordinal: int,
) -> dict[str, Any] | None:
    from yoke_core.domain.qa_plan_execution_store import result_rows

    for row in result_rows(conn, execution_id):
        if row["ordinal"] == ordinal:
            value = row["result"]
            return dict(value) if isinstance(value, dict) else None
    return None


def handle_agent_mission_ready(request: FunctionCallRequest) -> HandlerOutcome:
    target = target_plan_subject(request, "test_machine.mission.ready")
    if isinstance(target, HandlerOutcome):
        return target
    item_id, deployment_run_id = target
    parsed = parse_plan_case_request(
        AgentMissionPlanCaseReadyRequest,
        request.payload,
    )
    if isinstance(parsed, HandlerOutcome):
        return parsed
    assert isinstance(parsed, AgentMissionPlanCaseReadyRequest)

    from yoke_core.domain.coordination_claims import heartbeat
    from yoke_core.domain.db_helpers import connect
    from yoke_core.domain.machine_qa_capability import TestMachineCapabilityError
    from yoke_core.domain.machine_qa_execution_protocol import (
        MachineQaProtocolError,
        commit_deferred_connection,
        validate_host_control_submission,
    )
    from yoke_core.domain.machine_qa_submission_artifacts import (
        ensure_secret_free_result,
    )
    from yoke_core.domain.qa_plan_execution_state import advance_plan_execution

    conn = connect()
    try:
        execution, case = _owned_case(
            conn,
            request,
            parsed,
            item_id,
            deployment_run_id,
            replay=True,
            expected_runner="agent_mission",
        )
        arguments = plan_case_contract_arguments(
            execution, case, ordinal=parsed.ordinal
        )
        lease, contract = validate_host_control_submission(
            conn,
            project=str(case["project"]),
            session_id=request.actor.session_id,
            actor_id=request.actor.actor_id,
            lease_id=parsed.lease_id,
            contract_digest=parsed.contract_digest,
            allow_recorded_replay=True,
            **arguments,
        )
        if (
            parsed.ordinal == int(execution["cursor_ordinal"])
            and execution.get("machine_lease_id") != lease.id
        ):
            raise ValueError("mission preparation names the wrong machine lease")
        recorded = _recorded_result(
            conn,
            execution_id=str(execution["id"]),
            ordinal=parsed.ordinal,
        )
        if recorded is not None:
            result = recorded
        else:
            preparation = parsed.preparation.model_dump(mode="json")
            ensure_secret_free_result(preparation)
            run_id, result = insert_mission_docket(
                conn,
                execution=execution,
                case=case,
                preparation=preparation,
                lease_id=lease.id,
                contract_digest=parsed.contract_digest,
            )
            advance_plan_execution(
                conn,
                execution,
                ordinal=parsed.ordinal,
                requirement_id=parsed.requirement_id,
                result=result,
                commit=False,
            )
            heartbeat(commit_deferred_connection(conn), lease.id)
            from yoke_core.domain.machine_operation_recording import (
                record_test_machine_baseline_reset,
            )

            outcome = preparation["evidence"].get("baseline_outcome")
            baseline_receipt = outcome.get("receipt") if outcome else preparation
            if baseline_receipt is not None:
                record_test_machine_baseline_reset(
                    conn,
                    contract,
                    baseline_receipt,
                    lease_id=lease.id,
                    contract_digest=parsed.contract_digest,
                )
            conn.commit()
            from yoke_core.domain import qa_events

            qa_events.emit_qa_run_event(
                conn,
                db_path=None,
                event_name="QARunCaptured",
                run_id=run_id,
                requirement_id=int(case["requirement_id"]),
                qa_kind=str(case["qa_kind"]),
                verdict=None,
            )
    except (MachineQaProtocolError, TestMachineCapabilityError, ValueError) as exc:
        conn.rollback()
        return _failure("agent_mission_ready_failed", str(exc))
    finally:
        conn.close()
    return HandlerOutcome(
        primary_success=True,
        result_payload={
            "execution_id": str(execution["id"]),
            "cursor_ordinal": int(execution["cursor_ordinal"]),
            "result": result,
        },
    )


def handle_agent_mission_access(request: FunctionCallRequest) -> HandlerOutcome:
    target = target_plan_subject(request, "test_machine.mission.access")
    if isinstance(target, HandlerOutcome):
        return target
    item_id, deployment_run_id = target
    parsed = parse_plan_case_request(AgentMissionAccessRequest, request.payload)
    if isinstance(parsed, HandlerOutcome):
        return parsed
    assert isinstance(parsed, AgentMissionAccessRequest)

    from yoke_core.domain.db_helpers import connect
    from yoke_core.domain.machine_qa_capability import TestMachineCapabilityError
    from yoke_core.domain.machine_qa_execution_protocol import MachineQaProtocolError
    from yoke_core.domain.machine_qa_plan_protocol import (
        continue_plan_host_control_execution,
    )
    from yoke_core.domain.qa_plan_execution_continuation import (
        mission_access_refusal,
    )
    from yoke_core.domain.qa_plan_execution_state import (
        heartbeat_plan_execution,
        lock_plan_execution,
        require_plan_execution_owner,
    )

    conn = connect()
    try:
        execution = lock_plan_execution(conn, parsed.execution_id)
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
        if execution["state"] != "awaiting_agent_review":
            raise ValueError(mission_access_refusal(conn, execution))
        matches = [
            (ordinal, case)
            for ordinal, case in enumerate(execution["roster"])
            if int(case["requirement_id"]) == parsed.requirement_id
            and case.get("runner_id") == "agent_mission"
        ]
        if len(matches) != 1 or execution.get("machine_lease_id") is None:
            raise ValueError("mission case has no active plan machine lease")
        ordinal, case = matches[0]
        _assert_current_snapshot(conn, case)
        from yoke_core.domain.qa_plan_host_leases import require_case_host_leases

        require_case_host_leases(conn, execution, case)
        arguments = plan_case_contract_arguments(execution, case, ordinal=ordinal)
        contract = continue_plan_host_control_execution(
            conn,
            project=str(case["project"]),
            session_id=request.actor.session_id,
            actor_id=request.actor.actor_id,
            lease_id=int(execution["machine_lease_id"]),
            baselines=arguments["baselines"],
            cases=arguments["cases"],
            plan_execution_id=arguments["plan_execution_id"],
            continues_execution_id=arguments["continues_execution_id"],
            roster_digest=arguments["roster_digest"],
            ordinal=arguments["ordinal"],
            case_position=arguments["case_position"],
            baseline_position=arguments["baseline_position"],
        )
        heartbeat_plan_execution(conn, execution)
    except (MachineQaProtocolError, TestMachineCapabilityError, ValueError) as exc:
        conn.rollback()
        return _failure("agent_mission_access_failed", str(exc))
    finally:
        conn.close()
    return HandlerOutcome(
        primary_success=True,
        result_payload={
            "execution_id": str(execution["id"]),
            "requirement_id": parsed.requirement_id,
            "execution": contract.model_dump(mode="json"),
        },
    )


def register(registry: Any) -> None:
    for function_id, handler, request_model, response_model, events in (
        (
            "test_machine.mission.ready",
            handle_agent_mission_ready,
            AgentMissionPlanCaseReadyRequest,
            AgentMissionPlanCaseReadyResponse,
            ["QARunCaptured", "YokeFunctionCalled"],
        ),
        (
            "test_machine.mission.access",
            handle_agent_mission_access,
            AgentMissionAccessRequest,
            AgentMissionAccessResponse,
            ["YokeFunctionCalled"],
        ),
    ):
        registry.register(
            function_id,
            handler,
            request_model,
            response_model,
            stability="stable",
            owner_module=__name__,
            target_kinds=["item", "deployment_run", "global"],
            minimum_serving_version="next-release",
            side_effects=["qa_plan_execution_write", "coordination_claim_heartbeat"],
            emitted_event_names=events,
            guardrails=[
                "qa_subject_authority",
                "actor_session_bound",
                "durable_plan_cursor",
                "secret_free_contract",
            ],
            adapter_status="internal",
            claim_required_kind="qa_subject",
            ambient_session_required=True,
        )
