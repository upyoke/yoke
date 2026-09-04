"""What each operator-run operation's issued contract contains.

Begin issues a contract, submit and abort rebuild the same contract to compare
its digest, and all three must agree on its shape or a correct client looks
like a tampering one. That agreement lives here rather than in three handlers.
"""

from __future__ import annotations

from typing import Any

from yoke_contracts.machine_qa_execution import (
    BRIDGE_DIAGNOSE_OPERATION,
    GOLDEN_CAPTURE_OPERATION,
    HOST_BASELINES,
    RESET_OPERATION,
    VERIFICATION_CHECKS,
    VERIFY_OPERATION,
)


#: The baseline a reset reaches when the caller names none. Fresh is the
#: default because it is the state an operator asks for when they say "give me
#: the box back": verification's own last baseline leaves Yoke installed.
DEFAULT_RESET_BASELINE = HOST_BASELINES[0]


class TestMachineOperationShapeError(ValueError):
    """The requested operation shape is not one the server issues."""


def operation_contract_shape(
    operation: str,
    *,
    baseline: str | None = None,
    golden_destination: str | None = None,
) -> dict[str, Any]:
    """Return the checks, baselines, and destination one operation carries."""
    if operation == VERIFY_OPERATION:
        return {
            "checks": list(VERIFICATION_CHECKS),
            "baselines": list(HOST_BASELINES),
            "golden_destination": None,
        }
    if operation == RESET_OPERATION:
        selected = baseline or DEFAULT_RESET_BASELINE
        if selected not in HOST_BASELINES:
            raise TestMachineOperationShapeError(
                f"{selected!r} is not a registered host baseline; choose one "
                "of " + ", ".join(HOST_BASELINES)
            )
        return {"checks": [], "baselines": [selected], "golden_destination": None}
    if operation == GOLDEN_CAPTURE_OPERATION:
        if not golden_destination:
            raise TestMachineOperationShapeError(
                "a golden capture names the directory it writes"
            )
        return {
            "checks": [],
            "baselines": [],
            "golden_destination": golden_destination,
        }
    if operation == BRIDGE_DIAGNOSE_OPERATION:
        return {"checks": [], "baselines": [], "golden_destination": None}
    raise TestMachineOperationShapeError(
        f"{operation!r} is not an operator-run test-machine operation"
    )


__all__ = [
    "DEFAULT_RESET_BASELINE",
    "TestMachineOperationShapeError",
    "operation_contract_shape",
]
