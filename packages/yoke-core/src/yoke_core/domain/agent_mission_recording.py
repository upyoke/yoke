"""Durable mission docket creation and leased walker access."""

from __future__ import annotations

import json
from typing import Any

from yoke_contracts.api.function_call import FunctionCallRequest, HandlerOutcome
from yoke_core.domain.handlers.machine_qa import _failure
from yoke_core.domain.handlers.machine_qa_plan_case import (
    _assert_current_snapshot,
    _contract_args,
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


def _recorded_result(
    conn: Any,
    *,
    execution_id: str,
    ordinal: int,
) -> dict[str, Any] | None:
    from yoke_core.domain.db_helpers import query_one
    from yoke_core.domain.qa_plan_execution_store import marker

    row = query_one(
        conn,
        "SELECT result_json FROM qa_plan_execution_results "
        f"WHERE execution_id={marker(conn)} AND ordinal={marker(conn)}",
        (execution_id, ordinal),
    )
    if row is None:
        return None
    value = json.loads(str(row["result_json"] or "{}"))
    return dict(value) if isinstance(value, dict) else None


def _insert_docket(
    conn: Any,
    *,
    execution: dict[str, Any],
    case: dict[str, Any],
    preparation: dict[str, Any],
    lease_id: int,
    contract_digest: str,
) -> tuple[int, dict[str, Any]]:
    from yoke_core.domain.db_helpers import iso8601_now
    from yoke_core.domain.machine_qa_execution_protocol import (
        host_control_submission_receipt,
    )
    from yoke_core.domain.qa_plan_execution_store import canonical, marker

    now = iso8601_now()
    executor = str(case["method_config"]["executor"])
    transcript = {
        "executor": executor,
        "preparation": preparation,
        "plan_execution_id": str(execution["id"]),
        "host_control_submission": host_control_submission_receipt(
            lease_id,
            contract_digest,
        ),
    }
    p = marker(conn)
    row = conn.execute(
        "INSERT INTO qa_runs(qa_requirement_id,performed_by,qa_kind,verdict,"
        "execution_status,case_outcome,raw_result,started_at,completed_at,created_at) "
        f"VALUES({', '.join([p] * 10)}) RETURNING id",
        (
            int(case["requirement_id"]),
            "agent_mission",
            str(case["qa_kind"]),
            None,
            "captured",
            "needs_review",
            canonical(transcript),
            now,
            now,
            now,
        ),
    ).fetchone()
    run_id = int(row[0])
    result = {
        "requirement_id": int(case["requirement_id"]),
        "runner_id": "agent_mission",
        "run_id": run_id,
        "verdict": None,
        "case_outcome": "needs_review",
        "executor": executor,
        "preparation": preparation,
    }
    return run_id, result


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
        arguments = _contract_args(execution, case, ordinal=parsed.ordinal)
        lease, _contract = validate_host_control_submission(
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
            run_id, result = _insert_docket(
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
        require_plan_execution_owner(
            execution,
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
        arguments = _contract_args(execution, case, ordinal=ordinal)
        contract = continue_plan_host_control_execution(
            conn,
            project=str(case["project"]),
            session_id=request.actor.session_id,
            actor_id=request.actor.actor_id,
            lease_id=int(execution["machine_lease_id"]),
            baselines=arguments["baselines"],
            cases=arguments["cases"],
            plan_execution_id=arguments["plan_execution_id"],
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
    """Register the mission-specific plan protocol beside Test Machine."""
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
            target_kinds=["item", "deployment_run"],
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


__all__ = [
    "handle_agent_mission_access",
    "handle_agent_mission_ready",
    "register",
]
