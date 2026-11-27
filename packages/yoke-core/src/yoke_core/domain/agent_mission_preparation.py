"""Preparation results retain the last proven host state and safe failure evidence."""

from __future__ import annotations

from yoke_contracts.runtime_ports.qa_host_package_fixture import get_qa_host_package_fixture

from yoke_core.domain.qa_plan_execution_checkin import (
    checkin_busy,
    communication_unknown,
)

from collections.abc import Callable
from typing import Any

from yoke_contracts.machine_qa_failures import (
    HostControlLocalError,
    bounded_machine_qa_diagnostic,
    host_control_failure,
)
from yoke_contracts.qa_mission_scratch import mission_scratch_identity
from yoke_core.domain.machine_qa_chain_restore import failed_baseline_probe
from yoke_core.domain.machine_qa_mission_scratch import (
    MissionScratchStateUnknownError,
    mission_scratch_present,
)
from yoke_core.domain.machine_qa_chain_restore import (
    STARTING_STATE_RESTORE,
    restore_chain_start,
)
from yoke_core.domain.machine_qa_phase_heartbeat import (
    MachineQaAborted,
    check_abort,
    heartbeat_during,
)
from yoke_core.domain.qa_controller_candidate import stamp_controller_runtime
from yoke_contracts.machine_qa_result_safety import redact_machine_qa_value
from yoke_core.domain.machine_qa_submission_artifacts import ensure_secret_free_result



def mission_manages_packages(contract: Any) -> bool:
    if not contract.cases:
        return False
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


ABORT_ERROR_CODE = "qa_host_abort_requested"


def _abort_restore(
    contract: Any,
    execution: Any,
    baseline_proof: dict[str, Any] | None,
    progress_callback: Callable[[], None] | None,
) -> dict[str, Any]:
    """The cleanup receipt a cancelled preparation owes before custody settles.

    A baseline reached after the last host change already proves the case's
    starting state; otherwise the case's declared baseline is restored. A
    case without one records that no restoration is required.
    """
    case = contract.cases[0]
    if not case.host_baseline:
        return {"baseline": None, "restoration_required": False}
    if baseline_proof is not None:
        return {"restored": True, **baseline_proof}
    settings = getattr(contract, "settings", None) or {}
    with heartbeat_during(
        STARTING_STATE_RESTORE, progress_callback, propagate_abort=False
    ):
        return restore_chain_start(
            case,
            execution.reach_baseline,
            test_machine=str(settings.get("resource_name") or "TEST_MACHINE"),
        )


def prepare_mission(
    contract: Any,
    *,
    execution_factory: Callable[..., Any],
    scratch_factory: Callable[..., dict[str, Any]] | None = None,
    progress_callback: Callable[[], None] | None = None,
    refuse_existing_scratch: bool = False,
) -> dict[str, Any]:
    """Return a submittable result even when local host preparation fails.

    It runs when the plan records the mission's docket, whose receipt proves
    the declared baseline, and again at ``yoke qa mission walk-start``: a
    mission is walked after its plan's other cases, which may have changed
    the machine since. Only walk-start creates scratch, which marks a live walk.

    Each phase boundary checks for cancellation; a blocking phase finishes
    first. A cancelled preparation stops, restores the case's declared
    baseline unless it was just proven, and returns that
    ``starting_state_restore`` receipt so the plan can settle the abort.

    Opening the execution can power on a cloud Test Machine, so the runner
    checks in first: that check-in puts the admitted case's hosts, driver and
    companions, in in-flight custody before the power call. A refused check-in
    or a recorded cancellation stops here, before the host is touched, and
    raises to the caller. The power call beats like any blocking phase and is
    cancelled at its boundary.
    """
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
        "evidence": stamp_controller_runtime(
            {"baseline_outcome": outcome, "scratch_created": False}
        ),
        # The Test Machine's OS owns where its scratch lives; until the host
        # creates it and names the path, report the scratch's identity
        # (servers require a non-empty value even when preparation fails).
        "scratch_path": mission_scratch_identity(str(contract.plan_execution_id)),
    }
    secrets: tuple[str, ...] = ()
    execution = None
    baseline_proof: dict[str, Any] | None = None
    try:
        check_abort(progress_callback)
    except Exception as error:
        if not communication_unknown(error):
            error.host_contact_possible = False  # Nothing has reached a host.
        raise
    try:
        phase = "credential_materialization"
        with heartbeat_during(
            "test_machine_power_on", progress_callback, propagate_abort=False
        ):
            execution = execution_factory(
                contract, progress_callback=progress_callback
            )
        secrets = tuple(execution.material.secrets.values())
        phase = "preparation_heartbeat"
        check_abort(progress_callback)
        execution_id = str(contract.plan_execution_id)
        if refuse_existing_scratch:
            phase = "mission_scratch_probe"
            try:
                started = mission_scratch_present(
                    execution.control, execution_id=execution_id
                )
            except MissionScratchStateUnknownError as error:
                raise HostControlLocalError(
                    code="mission_scratch_state_unknown",
                    phase=phase,
                    detail=str(error),
                    secrets=secrets,
                    recovery_hint="Restore Test Machine access, then rerun walk-start",
                ) from error
            if started:
                raise HostControlLocalError(
                    code="mission_walk_already_started",
                    phase=phase,
                    detail="This execution already has mission scratch on the host",
                    secrets=secrets,
                    recovery_hint=(
                        "Continue with yoke qa mission host-command, or run "
                        "yoke qa mission walk-end first to reset on purpose"
                    ),
                )

        from yoke_contracts.qa_continuity_fingerprint import check_continuity
        from yoke_core.domain.machine_reset_recovery import (
            owed_reset_refusal,
            recover_owed_reset,
        )

        phase = "owed_reset"
        with heartbeat_during(phase, progress_callback):
            owed = recover_owed_reset(contract, execution)
        if owed is not None:
            preparation["evidence"]["owed_reset"] = owed
            refusal = owed_reset_refusal(
                contract, owed, consequence="do not walk this mission", secrets=secrets
            )
            if refusal is not None:
                raise refusal

        if (
            not baseline_name
            and "continuity_fingerprint" in contract.cases[0].method_config
        ):
            phase = "continuity_fingerprint"
            continuity = check_continuity(
                execution.control, contract.cases[0].method_config
            )
            preparation["evidence"]["continuity_fingerprint"] = continuity
        phase = "preparation_heartbeat"
        check_abort(progress_callback)
        if baseline_name:
            phase = "baseline"
            outcome["state"] = "started"
            # The blocking reset settles before cancellation is acted on.
            with heartbeat_during(
                "mission_baseline", progress_callback, propagate_abort=False
            ):
                baseline = execution.reach_baseline(baseline_name)
            outcome["receipt"] = {
                "baseline": baseline.name,
                "ok": baseline.ok,
                "error_code": baseline.error_code,
                "evidence": baseline.evidence,
            }
            if baseline.ok:
                outcome["state"] = "completed"
                baseline_proof = dict(outcome["receipt"])
            else:
                evidence = baseline.evidence
                user_equivalence = evidence.get("user_equivalence") or {}
                exit_code = evidence.get("exit_code")
                if exit_code is None:
                    exit_code = user_equivalence.get("exit_code")
                if exit_code is None:
                    probe = failed_baseline_probe(evidence) or failed_baseline_probe(
                        user_equivalence
                    )
                    exit_code = probe.get("exit_code") if probe else None
                raise HostControlLocalError(
                    code=baseline.error_code or "baseline_operation_failed",
                    phase=phase,
                    detail=evidence.get("reason")
                    or user_equivalence.get("reason")
                    or "Baseline restore did not prove the requested host state",
                    exit_code=exit_code,
                    stdout=evidence.get("stdout", ""),
                    stderr=evidence.get("stderr") or str(evidence),
                    secrets=secrets,
                    recovery_hint=evidence.get("recovery")
                    or user_equivalence.get("recovery")
                    or "Inspect the baseline receipt and reconcile the host state before retrying QA.",
                )
            preparation["evidence"].update(baseline.evidence)
        phase = "preparation_heartbeat"
        check_abort(progress_callback)
        phase = "disk_preflight"
        preparation["evidence"]["disk_preflight"] = (
            execution.control.require_mission_disk_space()
        )
        check_abort(progress_callback)
        if mission_manages_packages(contract) and not contract.continues_execution_id:
            restore_host_packages = get_qa_host_package_fixture().restore_host_packages

            phase = "os_packages"
            baseline_proof = None  # Package restoration changes the host.
            preparation["evidence"]["os_packages"] = restore_host_packages(
                execution.control,
                contract.cases[0].method_config.get("host_starting_state"),
                secrets=secrets,
            )
            check_abort(progress_callback)
        else:
            preparation["evidence"]["os_packages"] = {}
        phase = "mission_scratch"
        if scratch_factory is None:
            preparation["scratch_path"] = execution.control.mission_scratch_path(
                execution_id
            )
        else:
            scratch = scratch_factory(execution.control, execution_id=execution_id)
            preparation["scratch_path"] = scratch["scratch_path"]
            preparation["evidence"]["scratch_created"] = True
    except MachineQaAborted as error:
        failure = {**_failure(error, phase, secrets), "error_code": ABORT_ERROR_CODE}
        preparation.update(ok=False, error_code=ABORT_ERROR_CODE)
        preparation["evidence"].update(
            preparation_failure=failure,
            abort={"reason": str(error), "host_work_stopped": True},
        )
        preparation["evidence"][STARTING_STATE_RESTORE] = _abort_restore(
            contract, execution, baseline_proof, progress_callback
        )
    except Exception as error:
        if communication_unknown(error) or checkin_busy(error):
            raise
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
    # A case that never started says nothing about the product: no verdict.
    return {
        **result,
        "verdict": None,
        "case_outcome": "blocked_on_precondition",
        "preparation": preparation,
        "error_code": preparation["error_code"],
        "error": failure["diagnostic"],
        "recovery": failure["recovery"],
    }
