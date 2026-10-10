"""Where each operator-run operation's receipt is written and read back.

Verification decides whether a machine is usable at all, so its receipt is the
verification row every availability surface reads. A reset, a capture, and a
diagnosis change what was last done to the machine without changing whether it
works, so they record beside it -- which is what lets the board show a fresh
box without calling it unverified.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from yoke_contracts.machine_qa_execution import (
    GOLDEN_CAPTURE_OPERATION,
    HostControlExecutionContract,
    VERIFY_OPERATION,
)
from yoke_core.domain.machine_operation_recording import (
    record_test_machine_operation,
    recorded_test_machine_operation,
)
from yoke_core.domain.machine_qa_golden_destination import (
    record_captured_golden_baseline,
    selected_test_machine_row,
)
from yoke_core.domain.machine_qa_operation_shape import (
    TestMachineOperationShapeError,
)
from yoke_core.domain.machine_verification_recording import (
    record_test_machine_verification,
    recorded_test_machine_verification,
)

if TYPE_CHECKING:
    from yoke_core.domain.handlers.machine_qa_operation import (
        TestMachineOperationSubmitRequest,
    )


def recorded_operation_receipt(
    conn: Any,
    *,
    parsed: TestMachineOperationSubmitRequest,
    contract: HostControlExecutionContract,
    lease_id: int,
    machine: str,
) -> dict[str, Any] | None:
    if parsed.operation == VERIFY_OPERATION:
        recorded = recorded_test_machine_verification(
            conn,
            contract.project_id,
            machine=machine,
            lease_id=lease_id,
            contract_digest=parsed.contract_digest,
        )
        return None if recorded is None else {"operation": VERIFY_OPERATION, **recorded}
    return recorded_test_machine_operation(
        conn,
        contract.project_id,
        machine=machine,
        operation=parsed.operation,
        lease_id=lease_id,
        contract_digest=parsed.contract_digest,
    )


def record_operation_receipt(
    conn: Any,
    *,
    parsed: TestMachineOperationSubmitRequest,
    contract: HostControlExecutionContract,
    lease_id: int,
    machine: str,
) -> dict[str, Any]:
    if parsed.operation == VERIFY_OPERATION:
        return {
            "operation": VERIFY_OPERATION,
            **record_test_machine_verification(
                conn,
                contract.project_id,
                machine=machine,
                status=parsed.status,
                checks=parsed.checks,
                error_code=parsed.error_code,
                lease_id=lease_id,
                contract_digest=parsed.contract_digest,
            ),
        }
    return record_test_machine_operation(
        conn,
        contract.project_id,
        machine=machine,
        operation=parsed.operation,
        status=parsed.status,
        checks=parsed.checks,
        error_code=parsed.error_code,
        lease_id=lease_id,
        contract_digest=parsed.contract_digest,
    )


def performed_at_row(recorded: dict[str, Any]) -> dict[str, Any]:
    """Report one time field whatever table the receipt was written to."""
    row = dict(recorded)
    checked_at = row.pop("checked_at", None)
    row.setdefault("performed_at", checked_at)
    return row


def record_capture_destination(
    conn: Any,
    *,
    contract: HostControlExecutionContract,
    parsed: TestMachineOperationSubmitRequest,
    machine: str,
) -> str | None:
    """Point the machine at a baseline the capture just proved, if it did."""
    if parsed.operation != GOLDEN_CAPTURE_OPERATION or parsed.status != "verified":
        return None
    destination = contract.golden_destination
    if destination is None:
        raise TestMachineOperationShapeError(
            "a golden capture receipt names the directory it wrote"
        )
    record_captured_golden_baseline(
        conn,
        selected_test_machine_row(conn, project=contract.project, machine=machine),
        destination=destination,
    )
    return destination


__all__ = [
    "performed_at_row",
    "record_capture_destination",
    "record_operation_receipt",
    "recorded_operation_receipt",
]
