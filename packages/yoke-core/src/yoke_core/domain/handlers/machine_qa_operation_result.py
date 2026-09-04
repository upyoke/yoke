"""Validate a submitted operation result against the contract that issued it.

A result is only evidence if it answers the question that was asked. Each
operation therefore states what its rows must be -- the issued check sequence
for verification, the issued baseline for a reset, the issued destination for a
capture, every bridge capability in order for a diagnosis -- so a client cannot
record a verdict about work the server never authorized.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from yoke_contracts.machine_qa_execution import (
    BRIDGE_DIAGNOSE_OPERATION,
    GOLDEN_CAPTURE_OPERATION,
    HostControlExecutionContract,
    RESET_OPERATION,
    VERIFICATION_CHECKS,
    VERIFY_OPERATION,
)
from yoke_contracts.machine_qa_terminal_bridge import TERMINAL_BRIDGE_CHECKS
from yoke_core.domain.machine_qa_submission_artifacts import (
    ensure_secret_free_result,
)


def _named_rows(checks: Sequence[Mapping[str, Any]]) -> tuple[list[str], list[bool]]:
    names: list[str] = []
    outcomes: list[bool] = []
    for check in checks:
        if not isinstance(check.get("name"), str):
            raise ValueError("result row is missing its registered name")
        if not isinstance(check.get("ok"), bool):
            raise ValueError("result row is missing its boolean result")
        names.append(str(check["name"]))
        outcomes.append(bool(check["ok"]))
    return names, outcomes


def _require_status(
    *,
    status: str,
    error_code: str | None,
    outcomes: Sequence[bool],
) -> None:
    if status == "verified":
        if not all(outcomes) or error_code is not None:
            raise ValueError("a passing result cannot carry a failed row")
    elif not str(error_code or "").strip() or all(outcomes):
        raise ValueError("a failing result must identify what failed")


def _validate_verification(
    parsed: Any,
    contract: HostControlExecutionContract,
) -> None:
    expected = [*contract.checks, *contract.baselines]
    names, outcomes = _named_rows(parsed.checks)
    if not names or names != expected[: len(names)]:
        raise ValueError("result does not follow the issued check sequence")
    if parsed.status == "verified" and names != expected:
        raise ValueError("verified result must pass every issued check")
    _require_status(
        status=parsed.status,
        error_code=parsed.error_code,
        outcomes=outcomes,
    )
    if parsed.status == "error" and (
        names[outcomes.index(False)] == VERIFICATION_CHECKS[0]
        and outcomes.index(False) != len(outcomes) - 1
    ):
        # Only the transport check is a precondition for the rest; a failure
        # there ends the sequence, while a later failure keeps going so the
        # host baselines still run.
        raise ValueError("a failed transport check ends the verification sequence")


def _validate_single_row(
    parsed: Any,
    *,
    expected_name: str,
) -> None:
    names, outcomes = _named_rows(parsed.checks)
    if names != [expected_name]:
        raise ValueError(f"result must report exactly {expected_name!r}")
    _require_status(
        status=parsed.status,
        error_code=parsed.error_code,
        outcomes=outcomes,
    )


def _validate_diagnosis(parsed: Any) -> None:
    names, outcomes = _named_rows(parsed.checks)
    if names != list(TERMINAL_BRIDGE_CHECKS):
        raise ValueError(
            "a bridge diagnosis reports every registered capability in order"
        )
    _require_status(
        status=parsed.status,
        error_code=parsed.error_code,
        outcomes=outcomes,
    )


def validate_operation_result(
    parsed: Any,
    contract: HostControlExecutionContract,
) -> None:
    """Refuse any result the issued contract did not ask for."""
    if parsed.operation == VERIFY_OPERATION:
        _validate_verification(parsed, contract)
    elif parsed.operation == RESET_OPERATION:
        _validate_single_row(parsed, expected_name=contract.baselines[0])
    elif parsed.operation == GOLDEN_CAPTURE_OPERATION:
        _validate_single_row(parsed, expected_name=GOLDEN_CAPTURE_OPERATION)
    elif parsed.operation == BRIDGE_DIAGNOSE_OPERATION:
        _validate_diagnosis(parsed)
    else:
        raise ValueError(
            f"{parsed.operation!r} is not an operator-run test-machine operation"
        )
    ensure_secret_free_result(parsed.model_dump(mode="json"))


__all__ = ["validate_operation_result"]
