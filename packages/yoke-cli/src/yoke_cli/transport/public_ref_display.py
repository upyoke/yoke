"""Emit public function responses in human and JSON modes.

Both modes omit internal item join keys, including when the serving build
predates public response composition. No client performs an id lookup.
"""

from __future__ import annotations

import json
import sys
from typing import Any, TextIO

from yoke_cli.transport.receipt_compaction import (
    compact_receipt,
    omission_advisory,
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
) -> int:
    from yoke_cli.transport.dispatcher import response_to_dict

    if json_mode:
        print(
            json.dumps(
                response_to_dict(prepare_human_response(response)), sort_keys=True
            )
        )
    else:
        display = prepare_human_response(response)
        if human_writer is not None and display.success:
            human_writer(display, sys.stdout, sys.stderr)
        else:
            _default_human_writer(display, sys.stdout, sys.stderr)
    return 0 if response.success else 1


def _default_human_writer(
    response: FunctionCallResponse, stdout: TextIO, stderr: TextIO
) -> None:
    if response.success:
        display, condensed = compact_receipt(response.function, response.result)
        print(json.dumps(display, sort_keys=True), file=stdout)
        if condensed:
            print(omission_advisory(condensed), file=stderr)
        for warning in response.warnings:
            print(
                f"warning: {warning.code} ({warning.step}): {warning.detail}",
                file=stderr,
            )
        return
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
    response = prepare_human_response(response)
    secrets = tuple(value for value in sensitive_values if value)
    if not secrets:
        return response

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

    return FunctionCallResponse.model_validate(
        redact(response.model_dump(mode="python"))
    )
