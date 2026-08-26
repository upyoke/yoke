"""Credential-local execution of server-issued host-control contracts."""

from __future__ import annotations

from pathlib import Path
import time
from collections.abc import Callable
from typing import Any

from yoke_harness.test_machine_verification import (
    LocalHostControlSubmission,
    execute_verification_contract as execute_client_verification_contract,
)
from yoke_harness.ssh_mac_gui_session import (
    classify_macos_session_context_failure,
)
from yoke_contracts.machine_qa_execution import GUI_SESSION_CONTEXT

from yoke_core.domain.coordination_claim_record import CoordinationClaim
from yoke_core.domain.work_claim_targets import make_qa_admission_target
from yoke_core.domain.host_control_runner import (
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
    *,
    progress_callback: Callable[[], None] | None = None,
) -> MachineQaLease:
    control, material = resolve_contract_host_control(
        {
            "project_id": contract.project_id,
            "project": contract.project,
            "settings": contract.settings,
        }
    )
    allowed_urls = tuple(
        str(value).rstrip("/")
        for case in contract.cases
        for key, value in case.execution_target["endpoints"].items()
        if key.endswith("_url") and isinstance(value, str) and value
    )
    return MachineQaLease(
        conn=None,
        control=control,
        material=material,
        lease=CoordinationClaim(
            id=contract.lease_id,
            target=make_qa_admission_target(
                contract.settings["resource_name"]
            ),
            session_id="server-owned",
            claimed_at="server-issued",
        ),
        owns_lease=False,
        progress_callback=progress_callback,
        allowed_operator_urls=allowed_urls,
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
    *,
    progress_callback: Callable[[], None] | None = None,
) -> LocalHostControlSubmission:
    """Run one case or one baseline group under its server-owned lease."""
    contract = HostControlExecutionContract.model_validate(raw_contract)
    if contract.operation not in {"case", "plan_case", "baseline_group"}:
        raise ValueError("expected a Machine QA case contract")
    execution = (
        _execution(contract)
        if progress_callback is None
        else _execution(contract, progress_callback=progress_callback)
    )
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


def prepare_agent_mission_contract(
    raw_contract: dict[str, Any],
    *,
    progress_callback: Callable[[], None] | None = None,
) -> dict[str, Any]:
    """Reach the mission baseline without executing an authored step list."""
    contract = HostControlExecutionContract.model_validate(raw_contract)
    if contract.operation != "plan_case" or (
        len(contract.cases) != 1
        or contract.cases[0].runner_id != "agent_mission"
    ):
        raise ValueError("expected an agent-mission plan-case contract")
    execution = _execution(contract, progress_callback=progress_callback)
    if progress_callback is not None:
        progress_callback()
    baseline = (
        execution.reach_baseline(contract.cases[0].host_baseline)
        if contract.cases[0].host_baseline
        else None
    )
    if progress_callback is not None:
        progress_callback()
    preparation = {
        "baseline": baseline.name if baseline else None,
        "ok": baseline.ok if baseline else True,
        "error_code": baseline.error_code if baseline else None,
        "evidence": baseline.evidence if baseline else {},
    }
    payload = {
        "lease_id": contract.lease_id,
        "contract_digest": contract.contract_digest,
        "preparation": redact_machine_qa_value(
            preparation,
            tuple(execution.material.secrets.values()),
        ),
    }
    ensure_secret_free_result(payload)
    return payload


def execute_agent_mission_host_command(
    raw_contract: dict[str, Any],
    *,
    argv: list[str],
    gui_session: bool,
    timeout_seconds: int,
) -> dict[str, Any]:
    """Run one lease-authorized walker command and return redacted output."""
    contract = HostControlExecutionContract.model_validate(raw_contract)
    if contract.operation != "plan_case" or (
        len(contract.cases) != 1
        or contract.cases[0].runner_id != "agent_mission"
    ):
        raise ValueError("expected an agent-mission plan-case contract")
    execution = _execution(contract)
    completed = execution.control.run_command(
        argv,
        required_session_context=GUI_SESSION_CONTEXT if gui_session else None,
        timeout=timeout_seconds,
    )
    context_failure = (
        classify_macos_session_context_failure(completed)
        if completed.returncode != 0 and not gui_session
        else None
    )
    result = {
        "exit_code": int(completed.returncode),
        "stdout": completed.stdout or "",
        "stderr": completed.stderr or "",
        "execution_context": "gui" if gui_session else "ssh",
        "session_context_degraded_reason": (
            context_failure.reason if context_failure is not None else None
        ),
        "session_context_error_code": (
            context_failure.error_code if context_failure is not None else None
        ),
    }
    redacted = redact_machine_qa_value(
        result,
        tuple(execution.material.secrets.values()),
    )
    ensure_secret_free_result(redacted)
    return redacted


__all__ = [
    "LocalHostControlSubmission",
    "execute_machine_case_contract",
    "execute_agent_mission_host_command",
    "prepare_agent_mission_contract",
    "execute_verification_contract",
]
