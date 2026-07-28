"""Credential-local execution of server-issued host-control contracts."""

from __future__ import annotations

from pathlib import Path
import time
from typing import Any

from yoke_harness.test_machine_verification import (
    LocalHostControlSubmission,
    execute_verification_contract as execute_client_verification_contract,
)

from yoke_core.domain.coordination_leases import Lease
from yoke_core.domain.host_control_executor import (
    resolve_contract_host_control,
)
from yoke_core.domain.machine_qa_execution import MachineQaLease
from yoke_core.domain.machine_qa_execution_contract import (
    HostControlExecutionContract,
)
from yoke_core.domain.machine_qa_fixture_lifecycle import (
    execute_case_with_fixture_lifecycle,
)
from yoke_core.domain.machine_qa_result_safety import (
    redact_machine_qa_value,
)
from yoke_core.domain.machine_qa_submission_artifacts import (
    ensure_secret_free_result,
    pack_local_artifacts,
)


def _execution(
    contract: HostControlExecutionContract,
) -> MachineQaLease:
    control, material = resolve_contract_host_control(
        {
            "project_id": contract.project_id,
            "project": contract.project,
            "settings": contract.settings,
        }
    )
    return MachineQaLease(
        conn=None,
        control=control,
        material=material,
        lease=Lease(
            id=contract.lease_id,
            project_id=contract.project_id,
            lease_key=contract.lease_key,
            session_id="server-owned",
            acquired_at="server-issued",
        ),
        owns_lease=False,
    )


class _CoreVerificationControl:
    """Adapt the full core execution runtime to the client-safe verifier."""

    def __init__(self, execution: MachineQaLease) -> None:
        self._execution = execution
        self.secret_values = tuple(execution.material.secrets.values())

    def check_connection(self) -> Any:
        return self._execution.control.check_connection()

    def check_terminal_bridge(self) -> Any:
        return self._execution.control.check_terminal_bridge()

    def reach_baseline(self, name: str) -> Any:
        return self._execution.reach_baseline(name)


def execute_verification_contract(
    raw_contract: dict[str, Any],
) -> LocalHostControlSubmission:
    """Run the exact verification checks named by the server contract."""
    return execute_client_verification_contract(
        raw_contract,
        control_factory=lambda contract: _CoreVerificationControl(_execution(contract)),
    )


def execute_machine_case_contract(
    raw_contract: dict[str, Any],
) -> LocalHostControlSubmission:
    """Run one case or one baseline group under its server-owned lease."""
    contract = HostControlExecutionContract.model_validate(raw_contract)
    if contract.operation not in {"case", "plan_case", "baseline_group"}:
        raise ValueError("expected a Machine QA case contract")
    execution = _execution(contract)
    result_payloads: list[dict[str, Any]] = []
    artifact_paths: list[Path] = []
    secret_values = tuple(execution.material.secrets.values())
    baseline_ok = True
    if contract.operation == "baseline_group":
        baseline_ok = execution.reach_baseline(contract.baselines[0]).ok
    for case in contract.cases:
        if contract.operation != "baseline_group" and case.host_baseline:
            baseline_ok = execution.reach_baseline(case.host_baseline).ok
        started = time.monotonic()
        result = execute_case_with_fixture_lifecycle(
            execution,
            case,
        )
        evidence, artifacts, paths = pack_local_artifacts(
            redact_machine_qa_value(result.evidence, secret_values)
        )
        artifact_paths.extend(paths)
        result_payloads.append(
            {
                "requirement_id": case.requirement_id,
                "case_outcome": result.case_outcome,
                "verdict": result.verdict,
                "evidence": evidence,
                "capture_degraded_reason": result.capture_degraded_reason,
                "error_code": result.error_code,
                "duration_ms": int((time.monotonic() - started) * 1000),
                "artifacts": [
                    artifact.model_dump(mode="json") for artifact in artifacts
                ],
            }
        )
    payload: dict[str, Any] = {
        "lease_id": contract.lease_id,
        "contract_digest": contract.contract_digest,
        "results": result_payloads,
    }
    if contract.operation == "baseline_group":
        payload["baseline_ok"] = baseline_ok
    ensure_secret_free_result(payload)
    return LocalHostControlSubmission(
        payload=payload,
        artifact_paths=tuple(artifact_paths),
    )


__all__ = [
    "LocalHostControlSubmission",
    "execute_machine_case_contract",
    "execute_verification_contract",
]
