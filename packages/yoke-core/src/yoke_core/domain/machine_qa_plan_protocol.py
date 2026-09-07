"""Issue later host-control contracts under a durable QA plan lease."""

from __future__ import annotations

from typing import Any, Sequence

from yoke_core.domain.machine_qa_execution_contract import (
    HostControlExecutionContract,
)
from yoke_core.domain.machine_qa_execution_protocol import (
    MachineQaProtocolError,
    _issue,
    _validate_lease_owner,
)
from yoke_core.domain.qa_plan_execution_continuation import contract_baselines


def plan_case_contract_arguments(
    execution: dict[str, Any], case: dict[str, Any], *, ordinal: int
) -> dict[str, Any]:
    """Build the execution-bound arguments for one immutable plan case."""
    contract_case = {key: value for key, value in case.items() if key != "ordinal"}
    return {
        "operation": "plan_case",
        "baselines": contract_baselines(execution, case),
        "cases": (contract_case,),
        "plan_execution_id": str(execution["id"]),
        "continues_execution_id": execution.get("continues_execution_id"),
        "roster_digest": str(execution["roster_digest"]),
        "ordinal": ordinal,
        "case_position": int(case["case_position"]),
        "baseline_position": int(case["baseline_position"]),
    }


def continue_plan_host_control_execution(
    conn: Any,
    *,
    project: str,
    session_id: str,
    actor_id: str | None,
    lease_id: int,
    baselines: Sequence[str],
    cases: Sequence[dict[str, Any]],
    plan_execution_id: str,
    continues_execution_id: str | None,
    roster_digest: str,
    ordinal: int,
    case_position: int,
    baseline_position: int,
    machine: str | None = None,
) -> HostControlExecutionContract:
    """Issue the next plan-case contract under its active host lease."""
    lease, selected = _validate_lease_owner(
        conn,
        project=project,
        session_id=session_id,
        actor_id=actor_id,
        lease_id=lease_id,
        allow_released=False,
    )
    selected_name = selected.settings["resource_name"]
    if machine and machine != selected_name:
        raise MachineQaProtocolError(
            "test_machine_constraint_mismatch: active plan lease uses "
            f"{selected_name!r}, but --machine named {machine!r}; rerun with "
            f"--machine {selected_name} or abort and restart the plan"
        )
    return _issue(
        selected,
        lease,
        operation="plan_case",
        checks=(),
        baselines=baselines,
        cases=cases,
        plan_execution_id=plan_execution_id,
        continues_execution_id=continues_execution_id,
        roster_digest=roster_digest,
        ordinal=ordinal,
        case_position=case_position,
        baseline_position=baseline_position,
    )


__all__ = ["continue_plan_host_control_execution", "plan_case_contract_arguments"]
