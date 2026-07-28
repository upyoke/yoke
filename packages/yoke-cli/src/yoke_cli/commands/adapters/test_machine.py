"""CLI adapters for the composite test-machine capability."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, List

from yoke_contracts.api.function_call import (
    FunctionCallResponse,
    FunctionError,
    TargetRef,
)
from yoke_cli.commands._helpers import (
    add_json_arg,
    add_session_arg,
    dispatch_and_emit,
    ensure_handlers_loaded,
    parse_or_usage_error,
    usage_error,
)
from yoke_cli.transport.dispatcher import (
    build_actor,
    call_dispatcher,
    emit_response,
)


GET_USAGE = "yoke test-machine get --project P [--json]"
SETTINGS_REPLACE_USAGE = (
    "yoke test-machine settings-replace --project P "
    "--settings-file FILE (--base AS_READ_JSON | --new) [--json]"
)
VERIFY_USAGE = "yoke test-machine verify --project P [--json]"


def _parser(prog: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=prog)
    parser.add_argument("--project", required=True)
    add_session_arg(parser)
    add_json_arg(parser)
    return parser


def _dispatch(
    parsed: argparse.Namespace,
    function_id: str,
    payload: dict[str, Any],
) -> int:
    return dispatch_and_emit(
        function_id=function_id,
        target=TargetRef(kind="global"),
        payload={"project": parsed.project, **payload},
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
    )


def test_machine_get(args: List[str]) -> int:
    parser = _parser("yoke test-machine get")
    parsed = parse_or_usage_error(parser, args, GET_USAGE)
    if parsed is None:
        return 2
    return _dispatch(parsed, "test_machine.get", {})


def test_machine_settings_replace(args: List[str]) -> int:
    parser = _parser("yoke test-machine settings-replace")
    parser.add_argument("--settings-file", required=True)
    base = parser.add_mutually_exclusive_group(required=True)
    base.add_argument("--base", dest="base_settings")
    base.add_argument("--new", action="store_true")
    parsed = parse_or_usage_error(parser, args, SETTINGS_REPLACE_USAGE)
    if parsed is None:
        return 2
    try:
        settings = json.loads(Path(parsed.settings_file).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return usage_error(f"settings file must be readable JSON: {exc}")
    if not isinstance(settings, dict):
        return usage_error("settings file root must be an object")
    return _dispatch(
        parsed,
        "test_machine.settings_replace",
        {
            "settings": settings,
            "base_settings": None if parsed.new else parsed.base_settings,
        },
    )


def test_machine_verify(args: List[str]) -> int:
    parser = _parser("yoke test-machine verify")
    parsed = parse_or_usage_error(parser, args, VERIFY_USAGE)
    if parsed is None:
        return 2
    ensure_handlers_loaded()
    actor = build_actor(session_id=parsed.session_id)
    begin = call_dispatcher(
        function_id="test_machine.verify.begin",
        target=TargetRef(kind="global"),
        payload={"project": parsed.project},
        actor=actor,
    )
    if not begin.success:
        return emit_response(
            _as_public_verify_response(begin),
            json_mode=parsed.json_mode,
        )
    execution = (begin.result or {}).get("execution")
    if not isinstance(execution, dict):
        return emit_response(
            _local_execution_error(
                "verification begin returned no execution contract",
            ),
            json_mode=parsed.json_mode,
        )
    try:
        from yoke_harness.test_machine_verification import (
            execute_verification_contract,
        )

        submission = execute_verification_contract(execution)
    except Exception as exc:
        released = _abort_verification(
            actor=actor,
            project=parsed.project,
            execution=execution,
            reason="local_execution_failed",
        )
        return emit_response(
            _local_execution_error(
                "local host-control verification failed "
                f"({type(exc).__name__}); "
                + (
                    "the server lease was released"
                    if released
                    else "automatic server-lease release also failed"
                ),
                lease_released=released,
            ),
            json_mode=parsed.json_mode,
        )
    try:
        submit = call_dispatcher(
            function_id="test_machine.verify.submit",
            target=TargetRef(kind="global"),
            payload={"project": parsed.project, **submission.payload},
            actor=actor,
        )
        if not submit.success:
            _abort_verification(
                actor=actor,
                project=parsed.project,
                execution=execution,
                reason="submission_failed",
            )
    finally:
        submission.cleanup_artifacts()
    return emit_response(
        _as_public_verify_response(submit),
        json_mode=parsed.json_mode,
    )


def _abort_verification(
    *,
    actor: Any,
    project: str,
    execution: dict[str, Any],
    reason: str,
) -> bool:
    lease_id = execution.get("lease_id")
    contract_digest = execution.get("contract_digest")
    if not isinstance(lease_id, int) or not isinstance(contract_digest, str):
        return False
    response = call_dispatcher(
        function_id="test_machine.verify.abort",
        target=TargetRef(kind="global"),
        payload={
            "project": project,
            "lease_id": lease_id,
            "contract_digest": contract_digest,
            "reason": reason,
        },
        actor=actor,
    )
    return bool(response.success)


def _as_public_verify_response(
    response: FunctionCallResponse,
) -> FunctionCallResponse:
    return response.model_copy(update={"function": "test_machine.verify"})


def _local_execution_error(
    message: str,
    *,
    lease_released: bool = False,
) -> FunctionCallResponse:
    return FunctionCallResponse(
        success=False,
        function="test_machine.verify",
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


USAGE_BY_FUNCTION_ID = {
    "test_machine.get": GET_USAGE,
    "test_machine.settings_replace": SETTINGS_REPLACE_USAGE,
    "test_machine.verify": VERIFY_USAGE,
}


__all__ = [
    "GET_USAGE",
    "SETTINGS_REPLACE_USAGE",
    "USAGE_BY_FUNCTION_ID",
    "VERIFY_USAGE",
    "test_machine_get",
    "test_machine_settings_replace",
    "test_machine_verify",
]
