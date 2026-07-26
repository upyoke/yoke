"""Lease, baseline, verdict, and evidence runtime for Machine QA methods."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from yoke_core.domain import db_backend
from yoke_core.domain.coordination_leases import (
    Lease,
    acquire_lease,
    release_lease,
)
from yoke_core.domain.db_helpers import iso8601_now
from yoke_core.domain.host_baseline_operations import (
    HostBaselineResult,
    run_host_baseline,
)
from yoke_core.domain.host_control_executor import (
    HostActionResult,
    HostControl,
    TestMachineMaterial,
    resolve_host_control,
)
from yoke_core.domain.machine_qa_method_contracts import (
    MACHINE_METHODS,
    MachineQaExecutionError,
    validate_machine_method_config,
)
from yoke_core.domain.test_machine_capability import lease_key
from yoke_core.domain.test_machine_schema import ensure_test_machine_schema


@dataclass(frozen=True)
class MachineCaseResult:
    case_outcome: str
    verdict: str
    evidence: dict[str, Any]
    capture_degraded_reason: str | None = None
    error_code: str | None = None


@dataclass
class MachineQaLease:
    """One critical section covering a baseline and all dependent cases."""

    conn: Any
    control: HostControl
    material: TestMachineMaterial
    lease: Lease
    baseline: HostBaselineResult | None = None
    closed: bool = False

    def reach_baseline(self, name: str) -> HostBaselineResult:
        if self.closed:
            raise MachineQaExecutionError("test-machine lease is closed")
        self.baseline = run_host_baseline(self.control, name)
        if not self.baseline.ok:
            _record_verification(
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
            return MachineCaseResult(
                case_outcome="blocked_on_precondition",
                verdict="blocked",
                error_code=self.baseline.error_code,
                evidence={
                    "executor_id": "host_control",
                    "machine": self.material.settings["resource_name"],
                    "baseline": self.baseline.evidence,
                    "case_started": False,
                },
            )
        config = validate_machine_method_config(
            method_id,
            method_config,
            entry_surface=entry_surface,
            required_completion=required_completion,
        )
        if method_id in {"terminal-check", "terminal-inspection"}:
            raw = self.control.run_terminal_case(
                entry_surface=str(entry_surface),
                required_completion=str(required_completion),
                steps=config["steps"],
                capture_checkpoints=config.get("capture_checkpoints", []),
            )
        else:
            raw = self.control.run_machine_assertions(config["assertions"])
        safe = _redact(raw.evidence, tuple(self.material.secrets.values()))
        evidence = {
            "executor_id": "host_control",
            "machine": self.material.settings["resource_name"],
            "method_id": method_id,
            "baseline": self.baseline.name if self.baseline else None,
            **safe,
        }
        if not raw.ok:
            return MachineCaseResult(
                case_outcome="failed",
                verdict="fail",
                evidence=evidence,
                error_code=raw.error_code or "machine_method_failed",
            )
        if method_id == "terminal-inspection":
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
    lease = acquire_lease(
        conn,
        material.project_id,
        lease_key(material.settings["resource_name"]),
        session_id,
        actor_id=actor_id,
    )
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
                checks.append({"name": baseline_name, "ok": baseline.ok, **baseline.evidence})
                if not baseline.ok:
                    error_code = baseline.error_code
                    break
        status = "verified" if error_code is None else "error"
        safe_checks = _redact(
            checks,
            tuple(execution.material.secrets.values()),
        )
        _record_verification(
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


def _record_verification(
    conn: Any,
    project_id: int,
    *,
    status: str,
    checks: Sequence[Mapping[str, Any]],
    error_code: str | None,
) -> None:
    ensure_test_machine_schema(conn)
    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    now = iso8601_now()
    receipt = json.dumps({"checks": list(checks)}, separators=(",", ":"), sort_keys=True)
    conn.execute(
        "INSERT INTO test_machine_verifications("
        "project_id,status,checked_at,receipt_json,error_code,updated_at"
        f") VALUES({marker},{marker},{marker},{marker},{marker},{marker}) "
        "ON CONFLICT(project_id) DO UPDATE SET "
        "status=EXCLUDED.status, checked_at=EXCLUDED.checked_at, "
        "receipt_json=EXCLUDED.receipt_json, error_code=EXCLUDED.error_code, "
        "updated_at=EXCLUDED.updated_at",
        (project_id, status, now, receipt, error_code, now),
    )
    conn.execute(
        "UPDATE project_capabilities SET verified_at="
        f"{marker} WHERE project_id={marker} AND type='test-machine'",
        (now if status == "verified" else None, project_id),
    )
    conn.commit()


def _redact(value: Any, secrets: Sequence[str]) -> Any:
    if isinstance(value, dict):
        return {str(key): _redact(item, secrets) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact(item, secrets) for item in value]
    if isinstance(value, tuple):
        return [_redact(item, secrets) for item in value]
    if isinstance(value, str):
        redacted = value
        for secret in secrets:
            if secret:
                redacted = redacted.replace(secret, "[REDACTED]")
        return redacted
    return value


__all__ = [
    "MACHINE_METHODS",
    "MachineCaseResult",
    "MachineQaExecutionError",
    "MachineQaLease",
    "acquire_machine_qa_lease",
    "validate_machine_method_config",
    "verify_test_machine",
]
