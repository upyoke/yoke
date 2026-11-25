"""Begin, run and settle host operations on the credential-owning workstation."""

from __future__ import annotations

import argparse
import importlib
from functools import partial
from pathlib import Path
from typing import Any

from yoke_contracts.api.function_call import (
    FunctionCallResponse,
    FunctionError,
    TargetRef,
)
from yoke_contracts.machine_qa_failures import host_control_failure
from yoke_cli.commands._helpers import (
    ensure_handlers_loaded,
    parse_or_usage_error,
    usage_error,
)
from yoke_cli.commands.adapters.test_machine_operation_help import (
    HOST_OPERATION_DESCRIPTIONS,
)
from yoke_cli.transport.dispatcher import (
    build_actor,
    call_dispatcher,
    emit_response,
)


def run_host_operation(
    args: list[str],
    *,
    prog: str,
    usage: str,
    operation: str,
    with_baseline: bool = False,
    with_destination: bool = False,
) -> int:
    """Parse the operator's arguments and run one operation end to end."""
    parser = argparse.ArgumentParser(prog=prog)
    parser.epilog = (
        "An awaiting Machine QA mission's holder uses its retained host lease "
        "for non-reset operations. Reset/verify refuse test_machine_cleanup_live_lease; "
        "finish or abort the owning mission first. Submit and abort keep borrowed leases for mission close-out. "
        "Foreign holders refuse; ask the mission holder or wait for it to finish. "
        "Calls outside a mission acquire and release their own exclusive lease."
    )
    parser.description = HOST_OPERATION_DESCRIPTIONS.get(operation)
    parser.add_argument(
        "--test-machine",
        metavar="TEST_MACHINE",
        help="Name of the test machine to use.",
    )
    if with_baseline:
        parser.add_argument("--baseline", help="Name of the baseline to restore.")
    if with_destination:
        parser.add_argument(
            "--destination",
            help=(
                "Remote golden capture path; defaults beside the current golden to "
                "<user>-home-YYYYMMDDTHHMMSSZ in UTC. Local path claims do not apply."
            ),
        )
        parser.add_argument(
            "--probes-file",
            help="Optional additional probe document; it must name every standard OS check. Omit to seal the standard checks. See .yoke/docs/verification/test-machines/host-provisioning.md.",
        )
    from yoke_cli.commands._helpers import add_json_arg, add_session_arg

    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, usage)
    if parsed is None:
        return 2
    probes_document: str | None = None
    probes_file = getattr(parsed, "probes_file", None)
    if probes_file:
        try:
            probes_document = Path(probes_file).read_text(encoding="utf-8")
        except OSError as exc:
            return usage_error(f"probes file must be readable: {exc}")
    return _execute(
        operation=operation,
        test_machine=parsed.test_machine,
        baseline=getattr(parsed, "baseline", None),
        destination=getattr(parsed, "destination", None),
        probes_document=probes_document,
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
    )


def _power() -> Any:
    return importlib.import_module("yoke_core.domain.cloud_machine_power")


def _native_windows_operations(contract):
    # The SSH transport alone cannot run the SYSTEM fixture undo.
    runner = importlib.import_module("yoke_core.domain.host_control_runner")
    factory = importlib.import_module("yoke_core.domain.machine_qa_host_control")
    material = runner.materialize_test_machine_contract(
        runner.TestMachineContract(contract.project_id, contract.project, contract.settings)
    )
    return factory.host_control_for(material)


def _execute(
    *,
    operation: str,
    test_machine: str | None,
    baseline: str | None,
    destination: str | None,
    probes_document: str | None,
    session_id: str | None,
    json_mode: bool,
) -> int:
    ensure_handlers_loaded()
    response = _run(
        operation=operation, test_machine=test_machine, baseline=baseline,
        destination=destination, probes_document=probes_document,
        actor=build_actor(session_id=session_id),
    )
    exit_code = emit_response(response, json_mode=json_mode)
    return 1 if response.success and response.result.get("status") == "error" else exit_code


def _run(
    *, operation, test_machine, baseline, actor, destination=None,
    probes_document=None, relay_env=None, automatic_reset=False,
) -> FunctionCallResponse:
    dispatch = partial(call_dispatcher, actor=actor, relay_env=relay_env)
    begin = dispatch(
        function_id="test_machine.operation.begin",
        target=TargetRef(kind="global"),
        payload={
            "test_machine": test_machine,
            "operation": operation,
            "baseline": baseline,
            "destination": destination,
            **({"automatic_reset": True} if automatic_reset else {}),
        },
    )
    if not begin.success:
        return _as_public(begin, operation)
    execution = (begin.result or {}).get("execution")
    if not isinstance(execution, dict):
        return _local_execution_error(operation, f"{operation} begin returned no execution contract")
    project = execution["project"]
    submission = None
    try:
        from yoke_harness.golden_snapshot_retention import (
            SnapshotRetentionError, retain_after_verified_capture,
        )
        from yoke_contracts.machine_qa_execution import HostControlExecutionContract
        from yoke_contracts.machine_qa_host_control import REGISTERED_GOLDENS_KEY
        from yoke_harness.host_operations import host_operations_for
        from yoke_harness.registered_golden_check import check_registered_goldens
        from yoke_harness.test_machine_operations import (
            execute_host_operation_contract,
        )

        power = _power()
        with power.power_dispatch_scope(actor=actor, relay_env=relay_env):
            power.power_on(execution["project"], execution["settings"])
            if registered := begin.result.get(
                REGISTERED_GOLDENS_KEY
            ):  # older servers: none
                contract = HostControlExecutionContract.model_validate(execution)
                check_registered_goldens(host_operations_for(contract)._run, registered, os_name=contract.settings["os"])
            operation_runner = execute_host_operation_contract
            if execution["settings"].get("os") == "windows" and operation in {"reset", "verify"}:
                operation_runner = partial(
                    execute_host_operation_contract,
                    operations_factory=_native_windows_operations,
                )
            submission = operation_runner(
                execution,
                probes_document=probes_document,
            )
        removed = retain_after_verified_capture(
            operation, True,
            {**begin.result, **submission.payload,
             "golden_baseline_path": execution.get("golden_destination")},
            execution,
        )
    except Exception as exc:
        if submission is not None:
            submission.cleanup_artifacts()
        released = abort_operation(
            actor=actor,
            project=project,
            operation=operation,
            baseline=baseline,
            execution=execution,
            reason="local_execution_failed", relay_env=relay_env,
        )
        error_code, message, recovery_hint = (
            (exc.code, exc.detail, exc.recovery)
            if isinstance(exc, SnapshotRetentionError)
            else host_control_failure(exc, phase=f"{operation}_execution")
        )
        lease_state = {
            True: "the server lease was released",
            False: "the mission host lease was retained",
            None: "automatic server-lease abort also failed",
        }
        return _local_execution_error(
            operation, f"{message}; {lease_state[released]}",
            error_code=error_code, recovery_hint=recovery_hint,
            lease_released=released is True, lease_retained=released is False,
        )
    try:
        submit = dispatch(
            function_id="test_machine.operation.submit",
            target=TargetRef(kind="global"),
            payload={
                "project": project,
                "baseline": baseline,
                "destination": execution.get("golden_destination"),
                **submission.payload,
            },
        )
        if not submit.success:
            abort_operation(
                actor=actor,
                project=project,
                operation=operation,
                baseline=baseline,
                execution=execution,
                reason="submission_failed", relay_env=relay_env,
            )
    finally:
        submission.cleanup_artifacts()
    if (
        operation == "screenshot"
        and submit.success
        and (submit.result or {}).get("status") == "verified"
    ):
        try:
            path = retain_screenshot(submission.payload)
            submit = submit.model_copy(
                update={"result": {**submit.result, "artifact_path": str(path)}}
            )
        except (OSError, ValueError) as exc:
            return _local_execution_error(
                operation,
                "Screenshot receipt was recorded, but its local PNG could not be saved: "
                + str(exc),
                error_code="screenshot_local_save_failed",
                recovery_hint="Repair the machine's private temp directory and retry screenshot.",
            )
    from yoke_harness.harness_cli_latest import warn_capture_behind_latest
    if removed is not None and submit.success:
        submit = submit.model_copy(
            update={"result": {**submit.result, "removed_snapshots": removed}}
        )
    warn_capture_behind_latest(operation, submit.result, submission.payload)
    return _as_public(submit, operation)


def retain_screenshot(payload):
    """Keep accepted PNG bytes in the same private free-path space reviewers use."""
    from yoke_contracts.free_paths import private_free_path
    from yoke_contracts.machine_screenshot import screenshot_png
    from yoke_contracts.owner_private_path import write_owner_private

    content, _size = screenshot_png(payload["artifacts"][0]["content_base64"])
    path = private_free_path("desktop.png", prefix="yoke-desktop.")
    write_owner_private(path, content)
    return path


def abort_operation(
    *,
    actor: Any,
    project: str,
    operation: str,
    baseline: str | None,
    execution: dict[str, Any],
    reason: str,
    relay_env: str | None = None,
) -> bool | None:
    """Return released/retained for an accepted abort, or None if it failed."""
    lease_id = execution.get("lease_id")
    contract_digest = execution.get("contract_digest")
    if not isinstance(lease_id, int) or not isinstance(contract_digest, str):
        return None
    response = call_dispatcher(
        function_id="test_machine.operation.abort",
        target=TargetRef(kind="global"),
        payload={
            "project": project,
            "lease_id": lease_id,
            "contract_digest": contract_digest,
            "operation": operation,
            "baseline": baseline,
            "destination": execution.get("golden_destination"),
            "reason": reason,
        },
        actor=actor, relay_env=relay_env,
    )
    return bool((response.result or {}).get("released")) if response.success else None


def _as_public(
    response: FunctionCallResponse,
    operation: str,
) -> FunctionCallResponse:
    return response.model_copy(update={"function": f"test_machine.{operation}"})


def _local_execution_error(
    operation: str,
    message: str,
    *,
    error_code: str = "host_control_local_execution_failed",
    recovery_hint: str | None = None,
    lease_released: bool = False,
    lease_retained: bool = False,
) -> FunctionCallResponse:
    return FunctionCallResponse(
        success=False,
        function=f"test_machine.{operation}",
        version="v1",
        error=FunctionError(
            code=error_code,
            message=message,
            recovery_hint=(
                (
                    recovery_hint
                    or "Retry the registered CLI command from the executing machine."
                )
                + (
                    ""
                    if lease_released or lease_retained
                    else " Inspect and release the named coordination lease "
                    "before retrying."
                )
            ),
        ),
    )


__all__ = ["abort_operation", "run_host_operation"]
