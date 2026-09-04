"""Credential-local execution of one server-issued test-machine operation.

The server issues a digest-bound contract naming exactly what to do; this runs
it on the machine that holds the host credential and hands back a secret-free
receipt. Every operation reports the same shape -- a status, an ordered list of
named check rows, and at most one error code -- so the server records, and the
board renders, one kind of receipt whatever was run.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import Any, Callable, Sequence

from yoke_contracts.machine_qa_execution import (
    BRIDGE_DIAGNOSE_OPERATION,
    GOLDEN_CAPTURE_OPERATION,
    HostControlExecutionContract,
    RESET_OPERATION,
    VERIFICATION_CHECKS,
    VERIFY_OPERATION,
)
from yoke_harness.host_operations import HostOperations, host_operations_for
from yoke_harness.machine_qa_result_safety import (
    ensure_secret_free_result,
    redact_machine_qa_value,
)
from yoke_harness.test_machine_types import HostActionResult


HostOperationsFactory = Callable[[HostControlExecutionContract], HostOperations]


@dataclass(frozen=True)
class LocalHostControlSubmission:
    """A secret-free payload plus local captures to clean after acceptance."""

    payload: dict[str, Any]
    artifact_paths: tuple[Path, ...] = ()

    def cleanup_artifacts(self) -> None:
        for path in self.artifact_paths:
            path.unlink(missing_ok=True)


def run_verification_sequence(
    *,
    checks: Sequence[tuple[str, Callable[[], HostActionResult]]],
    baselines: Sequence[tuple[str, Callable[[], HostActionResult]]],
) -> tuple[list[dict[str, Any]], str | None]:
    """Run every named step, reporting the first failure as the verdict.

    Only the first check is a precondition for the rest -- it proves the
    transport -- so its failure ends the run. A later failure is recorded and
    the sequence continues, because the host baselines still execute over a
    working transport and skipping them left a walk's credential residue on
    the machine while a screenshot problem was being diagnosed.
    """
    recorded: list[dict[str, Any]] = []
    error_code: str | None = None
    for position, (name, action) in enumerate(checks):
        try:
            result = action()
        except Exception:
            recorded.append({"name": name, "ok": False})
            error_code = error_code or f"{name}_failed"
        else:
            recorded.append({"name": name, "ok": result.ok, **result.evidence})
            if result.ok:
                continue
            error_code = error_code or result.error_code or f"{name}_failed"
        if position == 0:
            return recorded, error_code
    for name, reach in baselines:
        baseline = reach()
        recorded.append({"name": name, "ok": baseline.ok, **baseline.evidence})
        if not baseline.ok:
            error_code = error_code or baseline.error_code
            break
    return recorded, error_code


def _verify(
    contract: HostControlExecutionContract,
    operations: HostOperations,
    _probes_document: str | None,
) -> tuple[list[dict[str, Any]], str | None]:
    actions = {
        VERIFICATION_CHECKS[0]: operations.check_connection,
        VERIFICATION_CHECKS[1]: operations.check_terminal_bridge,
    }
    return run_verification_sequence(
        checks=[(name, actions[name]) for name in contract.checks],
        baselines=[
            (name, partial(operations.reach_baseline, name))
            for name in contract.baselines
        ],
    )


def _single_row(
    name: str, result: HostActionResult
) -> tuple[
    list[dict[str, Any]],
    str | None,
]:
    return (
        [{"name": name, "ok": result.ok, **result.evidence}],
        None if result.ok else (result.error_code or f"{name}_failed"),
    )


def _reset(
    contract: HostControlExecutionContract,
    operations: HostOperations,
    _probes_document: str | None,
) -> tuple[list[dict[str, Any]], str | None]:
    baseline = contract.baselines[0]
    return _single_row(baseline, operations.reach_baseline(baseline))


def _golden_capture(
    contract: HostControlExecutionContract,
    operations: HostOperations,
    probes_document: str | None,
) -> tuple[list[dict[str, Any]], str | None]:
    assert contract.golden_destination is not None
    return _single_row(
        GOLDEN_CAPTURE_OPERATION,
        operations.capture_golden_baseline(
            contract.golden_destination,
            probes_document=probes_document,
        ),
    )


def _bridge_diagnose(
    _contract: HostControlExecutionContract,
    operations: HostOperations,
    _probes_document: str | None,
) -> tuple[list[dict[str, Any]], str | None]:
    diagnosis = operations.diagnose_terminal_bridge()
    rows = [dict(row) for row in diagnosis.evidence.get("checks", [])]
    return rows, None if diagnosis.ok else diagnosis.error_code


OPERATION_RUNNERS: dict[
    str,
    Callable[
        [HostControlExecutionContract, HostOperations, str | None],
        tuple[list[dict[str, Any]], str | None],
    ],
] = {
    VERIFY_OPERATION: _verify,
    RESET_OPERATION: _reset,
    GOLDEN_CAPTURE_OPERATION: _golden_capture,
    BRIDGE_DIAGNOSE_OPERATION: _bridge_diagnose,
}


def execute_host_operation_contract(
    raw_contract: dict[str, Any],
    *,
    probes_document: str | None = None,
    operations_factory: HostOperationsFactory = host_operations_for,
) -> LocalHostControlSubmission:
    """Run exactly the operation the server issued and build its receipt."""
    contract = HostControlExecutionContract.model_validate(raw_contract)
    runner = OPERATION_RUNNERS.get(contract.operation)
    if runner is None:
        raise ValueError(
            f"{contract.operation!r} is not an operator-run test-machine "
            "operation; case execution has its own entry point"
        )
    operations = operations_factory(contract)
    checks, error_code = runner(contract, operations, probes_document)
    payload = {
        "lease_id": contract.lease_id,
        "contract_digest": contract.contract_digest,
        "operation": contract.operation,
        "status": "verified" if error_code is None else "error",
        "checks": redact_machine_qa_value(
            checks,
            tuple(operations.secret_values),
        ),
        "error_code": error_code,
    }
    ensure_secret_free_result(payload)
    return LocalHostControlSubmission(payload=payload)


__all__ = [
    "LocalHostControlSubmission",
    "OPERATION_RUNNERS",
    "execute_host_operation_contract",
    "run_verification_sequence",
]
