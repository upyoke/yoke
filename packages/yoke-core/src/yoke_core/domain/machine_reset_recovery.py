"""Credential-local recovery of a machine whose cleanup did not prove restoration."""

from yoke_contracts.machine_qa_failures import HostControlLocalError
from yoke_core.domain.machine_qa_chain_restore import baseline_receipt
from yoke_core.domain.machine_reset_debt import reset_command


def recover_owed_reset(contract, execution):
    baseline = getattr(contract, "reset_owed_baseline", None)
    if baseline is None:
        return None
    receipt = baseline_receipt(
        baseline,
        execution.reach_baseline,
        failure_code="machine_needs_repair",
    )
    if not receipt["ok"]:
        receipt.update(
            error_code="machine_needs_repair",
            recovery=reset_command(
                contract.project, contract.settings["resource_name"], baseline
            ),
        )
    return receipt


class MachineResetFailed(HostControlLocalError):
    """An owed reset failed before the case touched its host."""


def unstarted_reset_failure(
    case, test_machine, reset, *, error_code="starting_state_reset_failed"
):
    from yoke_core.domain.machine_qa_case_result import MachineCaseResult

    return MachineCaseResult(
        case_outcome="blocked_on_precondition",
        verdict="blocked",
        evidence={
            "runner_id": "host_control",
            "test_machine": test_machine,
            "baseline": case.host_baseline
            if case.starting_state == "baseline"
            else None,
            "case_started": False,
            "starting_state_reset": reset,
        },
        error_code=error_code,
    )
