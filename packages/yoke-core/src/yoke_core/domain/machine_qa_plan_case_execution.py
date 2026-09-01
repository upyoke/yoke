"""Client-local execution of one case inside a durable ordered QA plan."""

from __future__ import annotations

import sys
from typing import Any, Mapping

from yoke_contracts.api.function_call import ActorContext, TargetRef


class MachinePlanCaseDispatchError(RuntimeError):
    """A plan-scoped host-control case cannot complete its protocol."""


def _report_selection(begun: Mapping[str, Any], execution: Mapping[str, Any]) -> None:
    reason = execution.get("selection_reason")
    if begun.get("selection_new") and reason:
        print(f"# qa plan run: {reason}", file=sys.stderr, flush=True)


def _dispatch(
    function_id: str,
    *,
    target: TargetRef,
    actor: ActorContext,
    payload: dict[str, Any],
) -> dict[str, Any]:
    from yoke_core.domain.qa_composed_dispatch import call_qa_function

    response = call_qa_function(
        function_id=function_id,
        target=target,
        payload=payload,
        actor=actor,
    )
    if not response.success:
        code = response.error.code if response.error else "unknown"
        message = response.error.message if response.error else ""
        raise MachinePlanCaseDispatchError(f"{function_id} failed ({code}): {message}")
    return dict(response.result or {})


def execute_plan_machine_case(
    case: Mapping[str, Any],
    *,
    execution_id: str,
    ordinal: int,
    actor: ActorContext,
    machine: str | None = None,
) -> dict[str, Any]:
    """Run one server-issued host case without releasing the plan lease."""
    requirement_id = int(case.get("requirement_id") or 0)
    item_id = case.get("item_id")
    deployment_run_id = case.get("deployment_run_id")
    if requirement_id < 1 or bool(item_id) == bool(deployment_run_id):
        raise MachinePlanCaseDispatchError(
            "plan-scoped Machine QA requires one subject and a requirement id"
        )
    target = (
        TargetRef(kind="item", item_id=int(item_id))
        if item_id is not None
        else TargetRef(
            kind="deployment_run",
            deployment_run_id=str(deployment_run_id),
        )
    )
    request = {
        "execution_id": execution_id,
        "ordinal": int(ordinal),
        "requirement_id": requirement_id,
        **({"machine": machine} if machine else {}),
    }
    begun = _dispatch(
        "test_machine.plan_case.begin",
        target=target,
        actor=actor,
        payload=request,
    )
    if begun.get("state") == "waiting":
        return {
            "requirement_id": requirement_id,
            "runner_id": "host_control",
            "verdict": "waiting",
            "case_outcome": "waiting",
            "lease_context": begun.get("lease_context"),
        }
    execution = begun.get("execution")
    if begun.get("state") != "ready" or not isinstance(execution, dict):
        raise MachinePlanCaseDispatchError(
            "test_machine.plan_case.begin returned no execution contract"
        )
    _report_selection(begun, execution)
    submission = None
    try:
        from yoke_core.domain.machine_qa_local_execution import (
            execute_machine_case_contract,
        )
        from yoke_core.domain.ssh_mac_host_control import (
            register_ssh_mac_host_control,
        )

        register_ssh_mac_host_control()
        submission = execute_machine_case_contract(
            execution,
            progress_callback=lambda: _dispatch(
                "qa.plan_execution.heartbeat",
                target=target,
                actor=actor,
                payload={"execution_id": execution_id},
            ),
        )
        submitted = _dispatch(
            "test_machine.plan_case.submit",
            target=target,
            actor=actor,
            payload={**request, **submission.payload},
        )
    except Exception as exc:
        raise MachinePlanCaseDispatchError(
            f"plan-scoped local host-control execution failed ({type(exc).__name__})"
        ) from exc
    finally:
        if submission is not None:
            submission.cleanup_artifacts()
    result = submitted.get("result")
    if not isinstance(result, dict):
        raise MachinePlanCaseDispatchError(
            "test_machine.plan_case.submit returned no case result"
        )
    if int(result.get("requirement_id") or 0) != requirement_id:
        raise MachinePlanCaseDispatchError(
            "test_machine.plan_case.submit returned the wrong requirement"
        )
    return result


def execute_plan_agent_mission_case(
    case: Mapping[str, Any],
    *,
    execution_id: str,
    ordinal: int,
    actor: ActorContext,
    machine: str | None = None,
) -> dict[str, Any]:
    """Prepare one leased target and record its zero-artifact mission docket."""
    requirement_id = int(case.get("requirement_id") or 0)
    item_id = case.get("item_id")
    deployment_run_id = case.get("deployment_run_id")
    if requirement_id < 1 or bool(item_id) == bool(deployment_run_id):
        raise MachinePlanCaseDispatchError(
            "plan-scoped agent mission requires one subject and a requirement id"
        )
    target = (
        TargetRef(kind="item", item_id=int(item_id))
        if item_id is not None
        else TargetRef(kind="deployment_run", deployment_run_id=str(deployment_run_id))
    )
    request = {
        "execution_id": execution_id,
        "ordinal": int(ordinal),
        "requirement_id": requirement_id,
        **({"machine": machine} if machine else {}),
    }
    begun = _dispatch(
        "test_machine.plan_case.begin",
        target=target,
        actor=actor,
        payload=request,
    )
    if begun.get("state") == "waiting":
        return {
            "requirement_id": requirement_id,
            "runner_id": "agent_mission",
            "verdict": "waiting",
            "case_outcome": "waiting",
            "lease_context": begun.get("lease_context"),
        }
    execution = begun.get("execution")
    if begun.get("state") != "ready" or not isinstance(execution, dict):
        raise MachinePlanCaseDispatchError(
            "test_machine.plan_case.begin returned no mission contract"
        )
    _report_selection(begun, execution)
    try:
        from yoke_core.domain.machine_qa_local_execution import (
            prepare_agent_mission_contract,
        )
        from yoke_core.domain.ssh_mac_host_control import (
            register_ssh_mac_host_control,
        )

        register_ssh_mac_host_control()
        prepared = prepare_agent_mission_contract(
            execution,
            progress_callback=lambda: _dispatch(
                "qa.plan_execution.heartbeat",
                target=target,
                actor=actor,
                payload={"execution_id": execution_id},
            ),
        )
        submitted = _dispatch(
            "test_machine.mission.ready",
            target=target,
            actor=actor,
            payload={**request, **prepared},
        )
    except Exception as exc:
        raise MachinePlanCaseDispatchError(
            f"plan-scoped agent mission preparation failed ({type(exc).__name__})"
        ) from exc
    result = submitted.get("result")
    if not isinstance(result, dict) or (
        int(result.get("requirement_id") or 0) != requirement_id
    ):
        raise MachinePlanCaseDispatchError(
            "test_machine.mission.ready returned an invalid case result"
        )
    return result


__all__ = [
    "MachinePlanCaseDispatchError",
    "execute_plan_machine_case",
    "execute_plan_agent_mission_case",
]
