"""Emit public function responses in human and JSON modes.

Both modes omit internal item join keys, including when the serving build
predates public response composition. No client performs an id lookup.
"""

from __future__ import annotations

import json
import io
import sys
from typing import Any, TextIO

from yoke_cli.transport.human_values import write_human
from yoke_cli.transport.response_evidence import (
    save_response,
)
from yoke_contracts.api.function_call import FunctionCallResponse


def prepare_human_response(response: FunctionCallResponse) -> FunctionCallResponse:
    """Keep public identities supplied by this or an older serving build."""
    from yoke_contracts.public_item_contract import project_public_identities

    return response.model_copy(
        update={
            "result": project_public_identities(response.result, lambda _id: None),
        }
    )


def emit_response(
    response: FunctionCallResponse,
    *,
    json_mode: bool,
    human_writer=None,
    failure_writer=None,
    full: bool = False,
    machine_mode: bool = False,
) -> int:
    from yoke_cli.transport.dispatcher import response_to_dict

    from yoke_cli.transport.output_limit import (
        output_exceeds_limit,
        read_recovery,
        reply_exceeds_limit,
    )

    stdout, stderr = io.StringIO(), io.StringIO()
    if json_mode:
        print(
            json.dumps(
                response_to_dict(prepare_human_response(response)), sort_keys=True
            ),
            file=stdout,
        )
    else:
        display = prepare_human_response(response)
        if human_writer is not None and display.success:
            human_writer(display, stdout, stderr)
            if not machine_mode and not stdout.getvalue().strip():
                write_human(display.result, stdout)
        elif failure_writer is not None and not display.success:
            failure_writer(display, stdout, stderr)
            _write_error(display, stderr)
        else:
            _default_human_writer(display, stdout, stderr)
    if not json_mode and not machine_mode:
        for warning in response.warnings:
            message = f"warning: {warning.code} ({warning.step}): {warning.detail}"
            if message not in stderr.getvalue():
                print(message, file=stderr)
        if reply_exceeds_limit(stdout.getvalue() + stderr.getvalue()):
            try:
                evidence = save_response(
                    response_to_dict(prepare_human_response(response)),
                    stdout.getvalue(),
                    stderr.getvalue(),
                )
            except OSError as exc:
                print(
                    f"error (response_evidence_unavailable): complete reply could not be saved: {exc}. Restore writable temporary storage and inspect the result through its read command; do not repeat a mutation.",
                    file=sys.stderr,
                )
                return 1
            # These are the explicit workflow delivery contracts, not guesses
            # about which arbitrary result keys might be redundant.
            essential = io.StringIO()
            result = response.result or {}
            if result.get("execution_instructions"):
                from yoke_cli.commands.adapters.workflow_execution_instructions import (
                    render_execution_instruction_block,
                )

                instructions = render_execution_instruction_block(
                    result["execution_instructions"]
                )
                if reply_exceeds_limit(instructions):
                    essential.write(
                        f"Operator execution instructions apply: read {evidence} response.result.execution_instructions before continuing.\n"
                    )
                else:
                    essential.write(instructions)
            if result.get("handoff"):
                write_human({"handoff": result["handoff"]}, essential)
            essential.write(stderr.getvalue())
            summary = (
                f"{response.function}: {'completed' if response.success else 'refused'}. Complete reply saved: {evidence}\n"
                f"Read {evidence} for all result fields, instructions, stdout and stderr. The command already ran.\n"
                f"{read_recovery(response.function)}\n"
            )
            if reply_exceeds_limit(summary + essential.getvalue()):
                print(
                    f"error (essential_output_limit_exceeded): recovery or warnings exceed the display limit. Read the complete reply at {evidence}; resolve its named cause before continuing.",
                    file=sys.stderr,
                )
                return 1
            sys.stdout.write(summary)
            sys.stderr.write(essential.getvalue())
            return 0 if response.success else 1
    if (
        json_mode
        and not machine_mode
        and output_exceeds_limit(
            response.function, stdout.getvalue(), stderr.getvalue(), full=full
        )
    ):
        try:
            evidence = save_response(
                response_to_dict(prepare_human_response(response)),
                stdout.getvalue(),
                stderr.getvalue(),
            )
        except OSError as exc:
            print(
                f"error (response_evidence_unavailable): {exc}. Restore writable temporary storage; inspect the result before repeating a mutation.",
                file=sys.stderr,
            )
            return 1
        pointer = {
            "success": response.success,
            "function": response.function,
            "saved_response": str(evidence),
            "read": read_recovery(response.function),
        }
        if response.error:
            pointer["error"] = response.error.code
            pointer["recovery"] = (
                "Read saved_response response.error before continuing."
            )
        print(json.dumps(pointer, ensure_ascii=False))
        return 0 if response.success else 1
    sys.stdout.write(stdout.getvalue())
    sys.stderr.write(stderr.getvalue())
    return 0 if response.success else 1


def _default_human_writer(
    response: FunctionCallResponse, stdout: TextIO, stderr: TextIO
) -> None:
    if response.success:
        write_human(response.model_dump(mode="python")["result"], stdout)
        return
    if response.result:
        write_human(response.result, stdout)
    _write_error(response, stderr)


def _write_error(response: FunctionCallResponse, stderr: TextIO) -> None:
    if response.error is not None:
        print(f"error ({response.error.code}): {response.error.message}", file=stderr)
        if response.error.recovery_hint:
            print(f"hint: {response.error.recovery_hint}", file=stderr)
    else:
        print("error: dispatch returned success=False", file=stderr)


__all__ = ["emit_response", "prepare_human_response"]


def redact_response(
    response: FunctionCallResponse,
    sensitive_values: tuple[str, ...],
) -> FunctionCallResponse:
    # Transport redacts secrets but preserves the server-owned machine payload.
    # Human identity projection belongs to emit_response, not dispatch.
    # Local dispatch has native result values; the same response serializer
    # owns the clock image consumed from local and HTTPS client responses.
    wire = response.model_dump(mode="python")
    secrets = tuple(value for value in sensitive_values if value)
    if not secrets:
        return FunctionCallResponse.model_validate(wire)

    def redact(value: Any) -> Any:
        if isinstance(value, str):
            for secret in secrets:
                value = value.replace(secret, "<redacted>")
            return value
        if isinstance(value, list):
            return [redact(item) for item in value]
        if isinstance(value, dict):
            return {key: redact(item) for key, item in value.items()}
        return value

    return FunctionCallResponse.model_validate(redact(wire))
