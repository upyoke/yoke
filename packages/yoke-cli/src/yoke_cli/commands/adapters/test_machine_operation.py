"""Drive one operator-run test-machine operation from the machine that can.

Every one of these operations reaches a real host over a credential that lives
on one workstation, so the control plane issues the contract and this executes
it locally: begin, run, submit, and -- when the local run fails -- abort, so a
machine is never left leased by an execution that has already stopped.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from yoke_contracts.api.function_call import (
    FunctionCallResponse,
    FunctionError,
    TargetRef,
)
from yoke_cli.commands._helpers import (
    ensure_handlers_loaded,
    parse_or_usage_error,
    usage_error,
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
    parser.add_argument("--project", required=True)
    parser.add_argument("--machine")
    if with_baseline:
        parser.add_argument("--baseline")
    if with_destination:
        parser.add_argument("--destination")
        parser.add_argument("--probes-file")
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
        project=parsed.project,
        machine=parsed.machine,
        baseline=getattr(parsed, "baseline", None),
        destination=getattr(parsed, "destination", None),
        probes_document=probes_document,
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
    )


def _execute(
    *,
    operation: str,
    project: str,
    machine: str | None,
    baseline: str | None,
    destination: str | None,
    probes_document: str | None,
    session_id: str | None,
    json_mode: bool,
) -> int:
    ensure_handlers_loaded()
    actor = build_actor(session_id=session_id)
    begin = call_dispatcher(
        function_id="test_machine.operation.begin",
        target=TargetRef(kind="global"),
        payload={
            "project": project,
            "machine": machine,
            "operation": operation,
            "baseline": baseline,
            "destination": destination,
        },
        actor=actor,
    )
    if not begin.success:
        return emit_response(_as_public(begin, operation), json_mode=json_mode)
    execution = (begin.result or {}).get("execution")
    if not isinstance(execution, dict):
        return emit_response(
            _local_execution_error(
                operation,
                f"{operation} begin returned no execution contract",
            ),
            json_mode=json_mode,
        )
    try:
        from yoke_harness.test_machine_operations import (
            execute_host_operation_contract,
        )

        submission = execute_host_operation_contract(
            execution,
            probes_document=probes_document,
        )
    except Exception as exc:
        released = abort_operation(
            actor=actor,
            project=project,
            operation=operation,
            baseline=baseline,
            execution=execution,
            reason="local_execution_failed",
        )
        return emit_response(
            _local_execution_error(
                operation,
                f"local host-control {operation} failed ({type(exc).__name__}); "
                + (
                    "the server lease was released"
                    if released
                    else "automatic server-lease release also failed"
                ),
                lease_released=released,
            ),
            json_mode=json_mode,
        )
    try:
        submit = call_dispatcher(
            function_id="test_machine.operation.submit",
            target=TargetRef(kind="global"),
            payload={
                "project": project,
                "baseline": baseline,
                "destination": execution.get("golden_destination"),
                **submission.payload,
            },
            actor=actor,
        )
        if not submit.success:
            abort_operation(
                actor=actor,
                project=project,
                operation=operation,
                baseline=baseline,
                execution=execution,
                reason="submission_failed",
            )
    finally:
        submission.cleanup_artifacts()
    return emit_response(_as_public(submit, operation), json_mode=json_mode)


def abort_operation(
    *,
    actor: Any,
    project: str,
    operation: str,
    baseline: str | None,
    execution: dict[str, Any],
    reason: str,
) -> bool:
    """Release the lease of an execution that stopped on this machine."""
    lease_id = execution.get("lease_id")
    contract_digest = execution.get("contract_digest")
    if not isinstance(lease_id, int) or not isinstance(contract_digest, str):
        return False
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
        actor=actor,
    )
    return bool(response.success)


def _as_public(
    response: FunctionCallResponse,
    operation: str,
) -> FunctionCallResponse:
    return response.model_copy(update={"function": f"test_machine.{operation}"})


def _local_execution_error(
    operation: str,
    message: str,
    *,
    lease_released: bool = False,
) -> FunctionCallResponse:
    return FunctionCallResponse(
        success=False,
        function=f"test_machine.{operation}",
        version="v1",
        error=FunctionError(
            code="host_control_local_execution_failed",
            message=message,
            recovery_hint=(
                "Verify this machine owns the test-machine ssh_private_key "
                "capability secret, then retry the CLI command."
                + (
                    ""
                    if lease_released
                    else " Inspect and release the named coordination lease "
                    "before retrying."
                )
            ),
        ),
    )


__all__ = ["abort_operation", "run_host_operation"]
