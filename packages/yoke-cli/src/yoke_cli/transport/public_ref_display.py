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
        requested_section,
        section_command,
    )
    from yoke_cli.transport.read_sections import section_outline, select_section

    section = requested_section() if response.success else None
    if section is not None and (json_mode or machine_mode):
        return _refuse(
            response,
            "read_section_requires_human_output",
            "--section selects one Markdown section of the human reply, so it "
            "cannot narrow a JSON or machine-format reply; nothing was printed.",
            "Drop --json to read the section, or drop --section to receive "
            "the complete envelope.",
            json_mode=json_mode,
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
    if section is not None:
        text = stdout.getvalue()
        selected = select_section(text, section)
        if selected is None:
            return _refuse(
                response,
                "read_section_missing",
                f"The reply has no section titled {section!r}; nothing was printed.",
                section_outline(text, section_command)
                or "The reply has no Markdown headings; drop --section to read it whole.",
            )
        stdout = io.StringIO(selected)
    if not json_mode and not machine_mode:
        for warning in response.warnings:
            message = f"warning: {warning.code} ({warning.step}): {warning.detail}"
            if message not in stderr.getvalue():
                print(message, file=stderr)
    if not json_mode and not machine_mode and output_exceeds_limit(
        response.function, stdout.getvalue(), stderr.getvalue(), full=full
    ):
        outline = section_outline(stdout.getvalue(), section_command)
        return _refuse(
            response,
            "read_output_limit_exceeded",
            "The rendered read exceeds the 28000-byte CLI output limit; no partial answer was printed.",
            read_recovery(response.function) + (f"\n{outline}" if outline else ""),
        )
    sys.stdout.write(stdout.getvalue())
    sys.stderr.write(stderr.getvalue())
    return 0 if response.success else 1


def _refuse(
    response: FunctionCallResponse,
    code: str,
    message: str,
    hint: str,
    *,
    json_mode: bool = False,
) -> int:
    """Replace a read's answer with a named refusal and its recovery."""
    from yoke_contracts.api.function_call import FunctionError

    refusal = response.model_copy(update={
        "success": False,
        "result": {},
        "warnings": [],
        "event_ids": [],
        "error": FunctionError(code=code, message=message, recovery_hint=hint),
    })
    return emit_response(refusal, json_mode=json_mode, full=True)


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
