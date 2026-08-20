"""Lease, baseline, verdict, and evidence runtime for Machine QA methods."""

from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Callable
from typing import Any, Mapping

from yoke_core.domain.coordination_leases import (
    Lease,
    LeaseHeldError,
    LeaseStaleHolderError,
    acquire_lease,
    active_lease,
    release_lease,
)
from yoke_core.domain.db_helpers import iso8601_now
from yoke_core.domain.host_baseline_operations import (
    HostBaselineResult,
    run_host_baseline,
)
from yoke_core.domain.host_control_runner import (
    HostActionResult,
    HostControl,
    TestMachineMaterial,
    resolve_host_control,
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
from yoke_core.domain.machine_qa_capability import lease_key
from yoke_core.domain.machine_qa_host_registrar import host_lease_project_id
from yoke_core.domain.machine_verification_recording import (
    record_test_machine_verification,
)


@dataclass
class MachineQaLease:
    """One critical section covering a baseline and all dependent cases."""

    conn: Any
    control: HostControl
    material: TestMachineMaterial
    lease: Lease
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
            release_lease(self.conn, self.lease.id, reason)
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
    actor_id: str | None = None,
) -> MachineQaLease:
    """Materialize the approved adapter, then acquire its resource lease."""
    control, material = resolve_host_control(conn, project=project)
    resource_name = str(material.settings["resource_name"])
    resource_lease_key = lease_key(resource_name)
    lease_project_id = host_lease_project_id(conn, resource_name)
    try:
        lease = acquire_lease(
            conn,
            lease_project_id,
            resource_lease_key,
            session_id,
            actor_id=actor_id,
        )
    except LeaseStaleHolderError as exc:
        raise MachineQaExecutionError(str(exc)) from None
    except LeaseHeldError as exc:
        held = active_lease(
            conn,
            lease_project_id,
            resource_lease_key,
        )
        if held is None:
            raise MachineQaExecutionError(
                "test-machine lease changed while acquiring; retry execution"
            ) from None
        raise MachineQaLeaseHeld(
            lease=held,
            machine=resource_name,
            contention=exc.contention,
        ) from None
    return MachineQaLease(
        conn=conn,
        control=control,
        material=material,
        lease=lease,
    )


def verify_test_machine(
    conn: Any,
    *,
    project: str,
    session_id: str,
    actor_id: str | None = None,
) -> dict[str, Any]:
    """Verify connection, control bridge, and both registered baselines."""
    checks: list[dict[str, Any]] = []
    error_code: str | None = None
    with acquire_machine_qa_lease(
        conn,
        project=project,
        session_id=session_id,
        actor_id=actor_id,
    ) as execution:
        for name, action in (
            ("connection", execution.control.check_connection),
            ("terminal_bridge", execution.control.check_terminal_bridge),
        ):
            try:
                result: HostActionResult = action()
            except Exception:
                checks.append({"name": name, "ok": False})
                error_code = f"{name}_failed"
                break
            checks.append({"name": name, "ok": result.ok, **result.evidence})
            if not result.ok:
                error_code = result.error_code or f"{name}_failed"
                break
        if error_code is None:
            for baseline_name in ("fresh-host", "shell-preconfigured"):
                baseline = execution.reach_baseline(baseline_name)
                checks.append(
                    {"name": baseline_name, "ok": baseline.ok, **baseline.evidence}
                )
                if not baseline.ok:
                    error_code = baseline.error_code
                    break
        status = "verified" if error_code is None else "error"
        safe_checks = redact_machine_qa_value(
            checks,
            tuple(execution.material.secrets.values()),
        )
        record_test_machine_verification(
            conn,
            execution.material.project_id,
            status=status,
            checks=safe_checks,
            error_code=error_code,
        )
    return {
        "project": project,
        "status": status,
        "checked_at": iso8601_now(),
        "checks": safe_checks,
        "error_code": error_code,
    }


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
    "verify_test_machine",
]
