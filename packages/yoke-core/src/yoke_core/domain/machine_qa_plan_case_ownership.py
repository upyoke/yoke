"""Ownership and snapshot checks for executing a plan case."""

from __future__ import annotations
from typing import Any
from yoke_contracts.api.function_call import FunctionCallRequest
from yoke_core.domain.machine_qa_plan_case_models import TestMachinePlanCaseBeginRequest
from yoke_core.domain.machine_qa_plan_case_snapshot import (
    assert_current_snapshot as _assert_current_snapshot,
)


def _owned_case(
    conn: Any,
    request: FunctionCallRequest,
    parsed: TestMachinePlanCaseBeginRequest,
    item_id: int | None,
    deployment_run_id: str | None,
    *,
    replay: bool,
    expected_runner: str | None = "host_control",
) -> tuple[dict[str, Any], dict[str, Any]]:
    from yoke_core.domain.qa_plan_execution_state import (
        expected_plan_case,
        lock_plan_execution,
        require_plan_execution_owner,
    )

    execution = lock_plan_execution(conn, parsed.execution_id)
    from yoke_core.domain.qa_execution_request_identity import resolve_execution_request

    request = resolve_execution_request(conn, request, execution)
    item_id, deployment_run_id = (
        request.target.item_id,
        request.target.deployment_run_id,
    )
    if request.target.kind == "global":
        from yoke_core.domain.qa_standalone_execution import require_standalone_project

        require_standalone_project(conn, execution, str(request.target.project_id))
    require_plan_execution_owner(
        execution,
        conn=conn,
        item_id=item_id,
        deployment_run_id=deployment_run_id,
        actor_id=request.actor.actor_id,
        session_id=request.actor.session_id,
    )
    case = expected_plan_case(
        execution,
        ordinal=parsed.ordinal,
        requirement_id=parsed.requirement_id,
        allow_replay=replay or expected_runner is None,
    )
    if expected_runner is not None and case.get("runner_id") != expected_runner:
        raise ValueError(f"the ordered plan case is not a {expected_runner} case")
    _assert_current_snapshot(conn, case)
    if replay and parsed.ordinal >= int(execution["cursor_ordinal"]):
        from yoke_core.domain.qa_plan_host_leases import require_case_host_leases

        require_case_host_leases(conn, execution, case)
    return execution, case
