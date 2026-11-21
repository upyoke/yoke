"""Durable custody of a reserved host during a borrowed operation."""

from yoke_core.domain.claim_chain_state import record_claim_reason

_BORROWED = ":operation:"


def turn_in_operation(claim) -> bool:
    from yoke_core.domain.qa_host_turns import HOST_TURN_REASON

    reason = claim.reason or ""
    return reason.startswith(HOST_TURN_REASON) and _BORROWED in reason


def borrow_turn(conn, claim, digest: str) -> None:
    from yoke_core.domain.machine_qa_execution_protocol import MachineQaProtocolError

    reason, _, running = claim.reason.partition(_BORROWED)
    if running and running != digest:
        raise MachineQaProtocolError(
            "qa_host_turn_operation_running: another operation is using this "
            "reservation; finish or abort it before retrying"
        )
    record_claim_reason(conn, claim_id=claim.id, reason=f"{reason}{_BORROWED}{digest}")


def finish_borrow(conn, claim, digest: str) -> None:
    """A replay cannot clear a different operation's custody."""
    reason, _, running = claim.reason.partition(_BORROWED)
    if running and running == digest:
        record_claim_reason(conn, claim_id=claim.id, reason=reason)
