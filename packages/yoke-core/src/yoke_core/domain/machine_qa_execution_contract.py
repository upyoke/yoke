"""Compatibility imports for the client-safe Machine QA execution contract."""

from yoke_contracts.machine_qa_execution import (
    HOST_CONTROL_PROTOCOL,
    HostControlExecutionContract,
    HostControlOperation,
    MachineQaCaseContract,
    HOST_BASELINES,
    VERIFICATION_CHECKS,
    execution_contract_digest,
    issue_execution_contract,
)


__all__ = [
    "HOST_CONTROL_PROTOCOL",
    "HostControlExecutionContract",
    "HostControlOperation",
    "MachineQaCaseContract",
    "HOST_BASELINES",
    "VERIFICATION_CHECKS",
    "execution_contract_digest",
    "issue_execution_contract",
]


def public_case_snapshots(cases):
    """Compose client identities before sealing the execution and target digests."""
    from yoke_contracts.api.function_call import FunctionCallResponse
    from yoke_core.domain.function_response_refs import public_response
    from yoke_core.domain.qa_execution_environment_target import target_digest

    snapshots = [dict(case) for case in cases]
    for case in snapshots:
        if "deployment_member_ref" in case:
            case["deployment_member_public_ref"] = case.pop("deployment_member_ref")
    response = public_response(
        FunctionCallResponse(
            success=True,
            function="test_machine.case.begin",
            version="v1",
            result={"cases": snapshots},
        )
    )
    if not response.success:
        raise ValueError(
            response.error.message
            if response.error
            else "Cannot compose Machine QA identities"
        )
    for case in response.result["cases"]:
        case["execution_target_digest"] = target_digest(case["execution_target"])
    return response.result["cases"]
