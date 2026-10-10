"""Credential-local execution of server-issued host-control contracts."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from yoke_harness.test_machine_operations import (
    LocalHostControlSubmission,
    execute_host_operation_contract as execute_client_host_operation_contract,
)
from yoke_harness.ssh_mac_gui_session import (
    classify_macos_session_context_failure,
)
from yoke_contracts.machine_qa_execution import GUI_SESSION_CONTEXT
from yoke_contracts.qa_mission_scratch import mission_scratch_path

from yoke_core.domain.agent_mission_preparation import (
    mission_manages_packages as _mission_manages_packages,
    prepare_mission,
)
from yoke_core.domain.coordination_claim_record import CoordinationClaim
from yoke_core.domain.work_claim_targets import make_qa_admission_target
from yoke_core.domain.host_control_runner import (
    resolve_contract_host_control,
)
from yoke_core.domain.machine_qa_execution import MachineQaLease
from yoke_core.domain.machine_qa_execution_contract import (
    HostControlExecutionContract,
)
from yoke_core.domain.machine_qa_chain_restore import (
    STARTING_STATE_RESET_FAILED,
    STARTING_STATE_RESTORE,
    baseline_receipt,
    restore_chain_start,
    restore_due,
    restore_summary,
)
from yoke_core.domain.machine_qa_fixture_lifecycle import (
    execute_case_with_fixture_lifecycle,
)
from yoke_core.domain.machine_qa_mission_scratch import create_mission_scratch
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
    control.baseline_preserved_temp_paths = tuple(
        mission_scratch_path(str(value))
        for value in (contract.plan_execution_id, contract.continues_execution_id)
        if value
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
            target=make_qa_admission_target(contract.settings["resource_name"]),
            session_id="server-owned",
            claimed_at="server-issued",
        ),
        owns_lease=False,
        progress_callback=progress_callback,
        allowed_operator_urls=allowed_urls,
    )


class _CoreHostOperations:
    """Adapt the full core execution runtime to the host-operation contract."""

    def __init__(self, execution: MachineQaLease) -> None:
        self._execution = execution
        self.secret_values = tuple(execution.material.secrets.values())

    def capture_screenshot(self) -> Any:
        return self._execution.control.capture_screenshot()

    def check_connection(self) -> Any:
        return self._execution.control.check_connection()

    def check_terminal_bridge(self) -> Any:
        return self._execution.control.check_terminal_bridge()

    def diagnose_terminal_bridge(self) -> Any:
        return self._execution.control.diagnose_terminal_bridge()

    def reach_baseline(self, name: str) -> Any:
        return self._execution.reach_baseline(name)

    def capture_golden_baseline(
        self,
        destination: str,
        *,
        probes_document: str | None = None,
    ) -> Any:
        return self._execution.control.capture_golden_baseline(
            destination,
            probes_document=probes_document,
        )


def execute_host_operation_contract(
    raw_contract: dict[str, Any],
    *,
    probes_document: str | None = None,
) -> LocalHostControlSubmission:
    """Run one operator-run operation through the core execution runtime."""
    return execute_client_host_operation_contract(
        raw_contract,
        probes_document=probes_document,
        operations_factory=lambda contract: _CoreHostOperations(_execution(contract)),
    )


def _unstarted_reset_failure(case: Any, machine: str, reset: dict[str, Any]) -> Any:
    from yoke_core.domain.machine_qa_case_result import MachineCaseResult

    return MachineCaseResult(
        case_outcome="blocked_on_precondition",
        verdict="blocked",
        evidence={
            "runner_id": "host_control",
            "machine": machine,
            "baseline": case.host_baseline,
            "case_started": False,
            "starting_state_reset": reset,
        },
        error_code=STARTING_STATE_RESET_FAILED,
    )


def execute_machine_case_contract(
    raw_contract: dict[str, Any],
    *,
    progress_callback: Callable[[], None] | None = None,
) -> LocalHostControlSubmission:
    """Run one case under its server-owned lease, inside its chain.

    The case resets to its declared baseline first when it opens a chain;
    a reset that does not prove the baseline leaves the case unstarted. The
    chain's starting state is restored after the case when it ends its chain
    or did not pass, including when local execution raises.
    """
    contract = HostControlExecutionContract.model_validate(raw_contract)
    if contract.operation not in {"case", "plan_case"}:
        raise ValueError("expected a Machine QA case contract")
    execution = (
        _execution(contract)
        if progress_callback is None
        else _execution(contract, progress_callback=progress_callback)
    )
    case = contract.cases[0]
    machine = contract.settings["resource_name"]
    secret_values = tuple(execution.material.secrets.values())
    started = time.monotonic()
    reset = (
        baseline_receipt(
            contract.baselines[0],
            execution.reach_baseline,
            failure_code=STARTING_STATE_RESET_FAILED,
        )
        if contract.baselines
        else None
    )
    try:
        if reset is not None and not reset["ok"]:
            result = _unstarted_reset_failure(case, machine, reset)
        else:
            result = execute_case_with_fixture_lifecycle(execution, case)
    except BaseException as exc:
        restore = restore_chain_start(case, execution.reach_baseline, machine=machine)
        exc.add_note(restore_summary(restore))
        raise
    evidence = dict(result.evidence)
    if restore_due(case, result.case_outcome):
        evidence[STARTING_STATE_RESTORE] = restore_chain_start(
            case, execution.reach_baseline, machine=machine
        )
    evidence, artifacts, artifact_paths = pack_local_artifacts(
        redact_machine_qa_value(evidence, secret_values)
    )
    payload: dict[str, Any] = {
        "lease_id": contract.lease_id,
        "contract_digest": contract.contract_digest,
        "results": [
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
        ],
    }
    ensure_secret_free_result(payload)
    return LocalHostControlSubmission(
        payload=payload,
        artifact_paths=tuple(artifact_paths),
    )


def _mission_contract(
    raw_contract: dict[str, Any],
) -> HostControlExecutionContract:
    """Validate one server-issued exploratory-mission plan-case contract."""
    contract = HostControlExecutionContract.model_validate(raw_contract)
    if contract.operation != "plan_case" or (
        len(contract.cases) != 1 or contract.cases[0].runner_id != "agent_mission"
    ):
        raise ValueError("expected an agent-mission plan-case contract")
    return contract


def prepare_agent_mission_contract(
    raw_contract: dict[str, Any],
    *,
    progress_callback: Callable[[], None] | None = None,
) -> dict[str, Any]:
    """Reach the mission baseline and stage its owner-only scratch."""
    return prepare_mission(
        _mission_contract(raw_contract),
        execution_factory=_execution,
        scratch_factory=create_mission_scratch,
        progress_callback=progress_callback,
    )


def execute_agent_mission_host_command(
    raw_contract: dict[str, Any],
    *,
    argv: list[str],
    gui_session: bool,
    timeout_seconds: int,
) -> dict[str, Any]:
    """Run one lease-authorized walker command and return redacted output."""
    contract = _mission_contract(raw_contract)
    execution = _execution(contract)
    from yoke_harness.qa_host_package_fixture import record_host_packages

    try:
        completed = execution.control.run_command(
            argv,
            required_session_context=GUI_SESSION_CONTEXT if gui_session else None,
            timeout=timeout_seconds,
        )
    finally:
        packages = (
            record_host_packages(execution.control)
            if _mission_manages_packages(contract)
            else {}
        )
    context_failure = (
        classify_macos_session_context_failure(completed)
        if completed.returncode != 0 and not gui_session
        else None
    )
    result = {
        "os_packages": packages,
        "exit_code": int(completed.returncode),
        "stdout": completed.stdout or "",
        "stderr": completed.stderr or "",
        "execution_context": "gui" if gui_session else "ssh",
        **(
            {"desktop_session": completed.desktop_session}
            if hasattr(completed, "desktop_session")
            else {}
        ),
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
    "execute_host_operation_contract",
]
