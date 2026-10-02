"""Preparation results retain the last proven host state and safe failure evidence."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from yoke_contracts.machine_qa_failures import (
    HostControlLocalError,
    bounded_machine_qa_diagnostic,
    host_control_failure,
)
from yoke_contracts.qa_mission_scratch import mission_scratch_path
from yoke_core.domain.machine_qa_result_safety import redact_machine_qa_value
from yoke_core.domain.machine_qa_submission_artifacts import ensure_secret_free_result


def mission_manages_packages(contract: Any) -> bool:
    case = contract.cases[0]
    return bool(case.host_baseline or case.method_config.get("host_starting_state"))


def _failure(error: Exception, phase: str, secrets: tuple[str, ...]) -> dict[str, Any]:
    code, message, recovery = host_control_failure(error, phase=phase)
    if (
        not isinstance(error, HostControlLocalError)
        and phase != "credential_materialization"
    ):
        message = f"{type(error).__name__}: {error}"
    return {
        "error_code": code,
        "phase": getattr(error, "phase", phase),
        "error_type": type(error).__name__,
        "diagnostic": bounded_machine_qa_diagnostic(message, secrets),
        "stdout": bounded_machine_qa_diagnostic(getattr(error, "stdout", ""), secrets),
        "stderr": bounded_machine_qa_diagnostic(getattr(error, "stderr", ""), secrets),
        "exit_code": getattr(error, "exit_code", getattr(error, "returncode", None)),
        "recovery": bounded_machine_qa_diagnostic(recovery, secrets),
    }


def prepare_mission(
    contract: Any,
    *,
    execution_factory: Callable[..., Any],
    scratch_factory: Callable[..., str],
    progress_callback: Callable[[], None] | None = None,
) -> dict[str, Any]:
    """Return a submittable result even when local host preparation fails."""
    baseline_name = contract.baselines[0] if contract.baselines else None
    outcome: dict[str, Any] = {
        "name": baseline_name,
        "state": "not_started",
        "receipt": None,
    }
    preparation: dict[str, Any] = {
        "baseline": baseline_name,
        "ok": True,
        "error_code": None,
        "evidence": {"baseline_outcome": outcome, "scratch_created": False},
        "scratch_path": mission_scratch_path(str(contract.plan_execution_id)),
    }
    secrets: tuple[str, ...] = ()
    phase = "credential_materialization"
    try:
        execution = execution_factory(contract, progress_callback=progress_callback)
        secrets = tuple(execution.material.secrets.values())
        phase = "preparation_heartbeat"
        if progress_callback is not None:
            progress_callback()
        if baseline_name:
            phase = "baseline"
            outcome["state"] = "started"
            baseline = execution.reach_baseline(baseline_name)
            outcome["receipt"] = {
                "baseline": baseline.name,
                "ok": baseline.ok,
                "error_code": baseline.error_code,
                "evidence": baseline.evidence,
            }
            if baseline.ok:
                outcome["state"] = "completed"
            else:
                raise HostControlLocalError(
                    code=baseline.error_code or "baseline_operation_failed",
                    phase=phase,
                    detail="Baseline restore did not prove the requested host state",
                    stderr=str(baseline.evidence),
                    secrets=secrets,
                    recovery_hint="Inspect the baseline receipt and reconcile the host state before retrying QA.",
                )
            preparation["evidence"].update(baseline.evidence)
        phase = "preparation_heartbeat"
        if progress_callback is not None:
            progress_callback()
        if mission_manages_packages(contract) and not contract.continues_execution_id:
            from yoke_harness.qa_host_package_fixture import restore_host_packages

            phase = "os_packages"
            preparation["evidence"]["os_packages"] = restore_host_packages(
                execution.control,
                contract.cases[0].method_config.get("host_starting_state"),
                secrets=secrets,
            )
        else:
            preparation["evidence"]["os_packages"] = {}
        phase = "mission_scratch"
        preparation["scratch_path"] = scratch_factory(
            execution.control, execution_id=str(contract.plan_execution_id)
        )
        preparation["evidence"]["scratch_created"] = True
    except Exception as error:
        failure = _failure(error, phase, secrets)
        preparation.update(ok=False, error_code=failure["error_code"])
        preparation["evidence"]["preparation_failure"] = failure
    payload = {
        "lease_id": contract.lease_id,
        "contract_digest": contract.contract_digest,
        "preparation": redact_machine_qa_value(preparation, secrets),
    }
    ensure_secret_free_result(payload)
    return payload


def preparation_failure_result(
    result: dict[str, Any], preparation: dict[str, Any]
) -> dict[str, Any]:
    """Expose a failed preparation in captures, including before server rollout."""
    if preparation["ok"]:
        return result
    failure = preparation["evidence"]["preparation_failure"]
    return {
        **result,
        "verdict": "error",
        "case_outcome": "blocked_on_precondition",
        "preparation": preparation,
        "error_code": preparation["error_code"],
        "error": failure["diagnostic"],
        "recovery": failure["recovery"],
    }
