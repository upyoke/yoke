"""A cancelled plan may borrow its retained hosts for proven baseline recovery."""

from yoke_contracts.timestamps import parse_instant
from yoke_core.domain.machine_qa_execution_protocol import (
    MachineQaProtocolError,
    _issue,
    validate_host_control_submission,
)
from yoke_core.domain.qa_plan_execution_abort_state import abort_request


def require_abort_reset(
    conn, execution, *, lease, project, actor, operation, baselines
):
    """Authorize only the interrupted baseline, without transferring custody."""
    request = abort_request(execution)
    if request is None:
        return False
    case = execution["roster"][int(request["ordinal"])]
    baseline = case.get("host_baseline")
    if (
        operation != "reset"
        or case.get("starting_state") == "as_is"
        or not baseline
        or list(baselines) != [baseline]
        or case.get("project") != project
    ):
        raise MachineQaProtocolError(
            "qa_abort_reset_required: cancellation retains host custody; stop the "
            "runner, reset this machine to the interrupted case's declared baseline "
            "with yoke test-machine reset --project P --machine NAME --baseline BASELINE, "
            "then retry yoke qa plan abort. Other operations cannot borrow this lease"
        )
    if not request.get("requested_at"):
        raise MachineQaProtocolError(
            "qa_abort_reset_checkpoint_required: retry yoke qa plan abort first "
            "to record the cancellation time, then reset and retry abort"
        )
    from yoke_core.domain.qa_plan_execution_store import same_owner
    from yoke_core.domain.host_control_runner import load_test_machine_contract
    from yoke_core.domain.session_steering_authority import covering_session_seat

    candidate = load_test_machine_contract(
        conn, project=project, machine=lease.target.machine_id
    )
    if not same_owner(execution, actor_id=actor.actor_id, session_id=actor.session_id):
        if (
            covering_session_seat(
                conn,
                caller_session_id=actor.session_id,
                target={
                    "project_id": candidate.project_id,
                    "item_id": execution.get("item_id"),
                },
            )
            is None
        ):
            raise MachineQaProtocolError(
                "qa_abort_reset_authority_required: recovery requires the lease-holding "
                "session or a live steering seat covering this project; route to yoke say --steering"
            )
    return True


def validate_operation_submission(conn, *, mission, actor, **shape):
    """An authorized recovery uses the plan's lease identity, never a new lease."""
    return validate_host_control_submission(
        conn,
        session_id=mission["session_id"] if mission else actor.session_id,
        actor_id=mission["actor_id"] if mission else actor.actor_id,
        **shape,
    )


def reset_cleanup_proven(conn, execution, baseline):
    """Every retained host needs a successful same-lease reset after cancellation."""
    from yoke_core.domain.coordination_claims import get_claim
    from yoke_core.domain.host_control_runner import load_test_machine_contract
    from yoke_core.domain.machine_operation_recording import (
        recorded_test_machine_operation,
    )
    from yoke_core.domain.qa_plan_host_leases import execution_host_leases

    request = abort_request(execution)
    if not request or not request.get("requested_at"):
        return False
    leases = {lease.id: lease for lease in execution_host_leases(conn, execution)}
    if execution.get("machine_lease_id") is not None:
        lease = get_claim(conn, int(execution["machine_lease_id"]))
        leases[lease.id] = lease
    if not leases:
        return False
    case = execution["roster"][int(request["ordinal"])]
    for lease in leases.values():
        candidate = load_test_machine_contract(
            conn,
            project=case["project"],
            machine=lease.target.machine_id,
        )
        contract = _issue(
            conn,
            candidate,
            lease,
            operation="reset",
            checks=(),
            baselines=[baseline],
            cases=(),
        )
        receipt = recorded_test_machine_operation(
            conn,
            candidate.project_id,
            machine=lease.target.machine_id,
            operation="reset",
            lease_id=lease.id,
            contract_digest=contract.contract_digest,
        )
        if not receipt or receipt["status"] != "verified" or receipt.get("error_code"):
            return False
        if parse_instant(receipt["performed_at"]) <= parse_instant(
            request["requested_at"]
        ):
            return False
        if receipt["checks"] != [] and all(
            check.get("name") == baseline and check.get("ok") is True
            for check in receipt["checks"]
        ):
            continue
        return False
    return True
