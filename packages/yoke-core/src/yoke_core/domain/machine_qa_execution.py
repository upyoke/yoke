"""Claim, baseline, verdict, and evidence runtime for Machine QA methods."""

from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Callable
from typing import Any, Mapping


from yoke_core.domain.coordination_claim_record import CoordinationClaim
from yoke_core.domain.coordination_claims import (
    CoordinationClaimStaleHolderError,
    release,
)
from yoke_core.domain.host_baseline_operations import (
    HostBaselineResult,
    run_host_baseline,
)
from yoke_core.domain.host_control_runner import (
    HostControl,
    TestMachineMaterial,
    resolve_contract_host_control,
)
from yoke_core.domain.machine_qa_method_contracts import (
    MACHINE_METHODS,
    MachineQaExecutionError,
    machine_method_definition,
    validate_machine_method_config,
)
from yoke_core.domain.machine_qa_case_result import (
    MachineCaseResult,
    MachineQaLeaseHeld,
)
from yoke_core.domain.machine_qa_result_safety import (
    redact_machine_qa_value,
)
from yoke_core.domain.machine_qa_host_selection import (
    TestMachineFleetBusy,
    acquire_test_machine,
)
from yoke_core.domain.machine_verification_recording import (
    record_test_machine_verification,
)


@dataclass
class MachineQaLease:
    """One critical section covering a baseline and all dependent cases."""

    conn: Any
    control: HostControl
    material: TestMachineMaterial
    lease: CoordinationClaim
    owns_lease: bool = True
    progress_callback: Callable[[], None] | None = None
    allowed_operator_urls: tuple[str, ...] = ()
    baseline: HostBaselineResult | None = None
    closed: bool = False

    def reach_baseline(self, name: str) -> HostBaselineResult:
        if self.closed:
            raise MachineQaExecutionError("test-machine lease is closed")
        self.baseline = run_host_baseline(self.control, name)
        if not self.baseline.ok and self.conn is not None and self.owns_lease:
            record_test_machine_verification(
                self.conn,
                self.material.project_id,
                machine=self.material.settings["resource_name"],
                status="error",
                checks=[self.baseline.evidence],
                error_code=self.baseline.error_code,
            )
        return self.baseline

    def execute(
        self,
        *,
        method_id: str,
        method_config: Mapping[str, Any],
        entry_surface: str | None,
        required_completion: str | None,
    ) -> MachineCaseResult:
        if self.closed:
            raise MachineQaExecutionError("test-machine lease is closed")
        if self.baseline is not None and not self.baseline.ok:
            baseline_evidence = redact_machine_qa_value(
                self.baseline.evidence,
                tuple(self.material.secrets.values()),
            )
            return MachineCaseResult(
                case_outcome="blocked_on_precondition",
                verdict="blocked",
                error_code=self.baseline.error_code,
                evidence={
                    "runner_id": "host_control",
                    "machine": self.material.settings["resource_name"],
                    "baseline": self.baseline.name,
                    "baseline_evidence": baseline_evidence,
                    "case_started": False,
                },
            )
        definition = machine_method_definition(method_id)
        config = validate_machine_method_config(
            method_id,
            method_config,
            entry_surface=entry_surface,
            required_completion=required_completion,
        )
        blocker = config.get("execution_blocker")
        if isinstance(blocker, Mapping):
            return MachineCaseResult(
                case_outcome="blocked_on_precondition",
                verdict="blocked",
                error_code=str(blocker["code"]),
                evidence={
                    "runner_id": "host_control",
                    "machine": self.material.settings["resource_name"],
                    "baseline": self.baseline.name if self.baseline else None,
                    "case_started": False,
                    "precondition": {
                        "code": str(blocker["code"]),
                        "reason": str(blocker["reason"]),
                    },
                },
            )
        if definition["config_contract_id"] in {
            "terminal-check",
            "terminal-inspection",
        }:
            if "actions" in config:
                raw = self.control.run_terminal_recipe(
                    entry_surface=str(entry_surface),
                    required_completion=str(required_completion),
                    config=config,
                    progress_callback=self.progress_callback,
                    allowed_operator_urls=self.allowed_operator_urls,
                )
            else:
                raw = self.control.run_terminal_case(
                    entry_surface=str(entry_surface),
                    required_completion=str(required_completion),
                    steps=config["steps"],
                    capture_checkpoints=config.get("capture_checkpoints", []),
                )
        else:
            raw = self.control.run_machine_assertions(config["assertions"])
        safe = redact_machine_qa_value(
            raw.evidence,
            tuple(self.material.secrets.values()),
        )
        evidence = {
            "runner_id": "host_control",
            "machine": self.material.settings["resource_name"],
            "method_id": method_id,
            "baseline": self.baseline.name if self.baseline else None,
            "baseline_evidence": (
                redact_machine_qa_value(
                    self.baseline.evidence,
                    tuple(self.material.secrets.values()),
                )
                if self.baseline is not None
                else None
            ),
            **safe,
        }
        if not raw.ok:
            return MachineCaseResult(
                case_outcome="failed",
                verdict="fail",
                evidence=evidence,
                error_code=raw.error_code or "machine_method_failed",
            )
        if definition["proof_kind"] == "terminal-inspection":
            degraded = str(safe.get("capture_degraded_reason") or "").strip() or None
            return MachineCaseResult(
                case_outcome="needs_review",
                verdict="pending",
                evidence=evidence,
                capture_degraded_reason=degraded,
            )
        return MachineCaseResult(
            case_outcome="passed",
            verdict="pass",
            evidence=evidence,
        )

    def close(self, reason: str = "machine-qa-complete") -> None:
        if self.closed:
            return
        if self.owns_lease:
            if self.conn is None:
                raise MachineQaExecutionError(
                    "owned test-machine lease has no authority connection"
                )
            release(self.conn, self.lease.id, reason)
        self.closed = True

    def __enter__(self) -> "MachineQaLease":
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close("machine-qa-failed" if exc_type else "machine-qa-complete")


def acquire_machine_qa_lease(
    conn: Any,
    *,
    project: str,
    session_id: str,
    machine: str | None = None,
    select_any: bool = True,
) -> MachineQaLease:
    """Materialize the approved adapter, then acquire its resource claim.

    The holding actor is the acquiring session's own actor, read from the
    session row rather than passed in, so a claim can never disagree with
    the identity that took it.
    """
    try:
        contract, lease = acquire_test_machine(
            conn,
            project=project,
            session_id=session_id,
            machine=machine,
            select_any=select_any,
        )
    except CoordinationClaimStaleHolderError as exc:
        raise MachineQaExecutionError(str(exc)) from None
    except TestMachineFleetBusy as exc:
        held = exc.busy[0]
        raise MachineQaLeaseHeld(
            lease=held.lease,
            machine=held.machine,
            contention=held.contention,
        ) from None
    try:
        control, material = resolve_contract_host_control(contract)
    except Exception:
        release(conn, lease.id, "machine-materialization-failed")
        raise
    return MachineQaLease(
        conn=conn,
        control=control,
        material=material,
        lease=lease,
    )


__all__ = [
    "MACHINE_METHODS",
    "MachineCaseResult",
    "MachineQaExecutionError",
    "MachineQaLease",
    "MachineQaLeaseHeld",
    "acquire_machine_qa_lease",
    "record_test_machine_verification",
    "redact_machine_qa_value",
    "validate_machine_method_config",
]
