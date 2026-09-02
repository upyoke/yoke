"""Credential-local execution of server-issued Test Machine verification."""

from __future__ import annotations

from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import Any, Callable, Protocol, Sequence

from yoke_contracts.machine_qa_execution import (
    HostControlExecutionContract,
    VERIFICATION_CHECKS,
)
from yoke_harness.machine_qa_result_safety import (
    ensure_secret_free_result,
    redact_machine_qa_value,
)
from yoke_harness.test_machine_types import HostActionResult


class VerificationControl(Protocol):
    """Closed machine-local operations required by verification."""

    secret_values: Sequence[str]

    def check_connection(self) -> HostActionResult: ...

    def check_terminal_bridge(self) -> HostActionResult: ...

    def reach_baseline(self, name: str) -> HostActionResult: ...


VerificationControlFactory = Callable[
    [HostControlExecutionContract],
    VerificationControl,
]


@dataclass(frozen=True)
class LocalHostControlSubmission:
    """A secret-free payload plus local captures to clean after acceptance."""

    payload: dict[str, Any]
    artifact_paths: tuple[Path, ...] = ()

    def cleanup_artifacts(self) -> None:
        for path in self.artifact_paths:
            path.unlink(missing_ok=True)


def _default_control(
    contract: HostControlExecutionContract,
) -> VerificationControl:
    from yoke_harness.ssh_mac_verification import SshMacVerificationControl

    return SshMacVerificationControl.from_contract(contract)


def run_verification_sequence(
    *,
    checks: Sequence[tuple[str, Callable[[], HostActionResult]]],
    baselines: Sequence[tuple[str, Callable[[], HostActionResult]]],
) -> tuple[list[dict[str, Any]], str | None]:
    """Run every named step, reporting the first failure as the verdict.

    Only the first check is a precondition for the rest — it proves the
    transport — so its failure ends the run. A later failure is recorded and
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


def execute_verification_contract(
    raw_contract: dict[str, Any],
    *,
    control_factory: VerificationControlFactory = _default_control,
) -> LocalHostControlSubmission:
    """Run the exact verification checks named by the server contract."""
    contract = HostControlExecutionContract.model_validate(raw_contract)
    if contract.operation != "verify":
        raise ValueError("expected a test-machine verification contract")
    control = control_factory(contract)
    actions = {
        VERIFICATION_CHECKS[0]: control.check_connection,
        VERIFICATION_CHECKS[1]: control.check_terminal_bridge,
    }
    checks, error_code = run_verification_sequence(
        checks=[(name, actions[name]) for name in contract.checks],
        baselines=[
            (name, partial(control.reach_baseline, name)) for name in contract.baselines
        ],
    )
    payload = {
        "lease_id": contract.lease_id,
        "contract_digest": contract.contract_digest,
        "status": "verified" if error_code is None else "error",
        "checks": redact_machine_qa_value(
            checks,
            tuple(control.secret_values),
        ),
        "error_code": error_code,
    }
    ensure_secret_free_result(payload)
    return LocalHostControlSubmission(payload=payload)


__all__ = [
    "LocalHostControlSubmission",
    "VerificationControl",
    "VerificationControlFactory",
    "execute_verification_contract",
    "run_verification_sequence",
]
