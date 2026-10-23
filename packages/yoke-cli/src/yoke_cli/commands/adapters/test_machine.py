"""CLI adapters for the composite test-machine capability."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, List

from yoke_contracts.api.function_call import FunctionCallResponse
from yoke_contracts.api.function_call import TargetRef
from yoke_contracts.machine_config.capability_secrets import (
    TEST_MACHINE_CAPABILITY,
)
from yoke_cli.commands._helpers import (
    add_json_arg,
    add_session_arg,
    dispatch_and_emit,
    parse_or_usage_error,
    usage_error,
)
from yoke_cli.config.capability_secrets import (
    list_machine_capability_secret_keys,
)
from yoke_contracts.machine_config.desktop_access import DESKTOP_PASSWORD_KEY
from yoke_cli.commands.adapters.test_machine_operation import run_host_operation
from yoke_cli.transport.test_machine_response_field import read_test_machine_field


LIST_USAGE = "yoke test-machine list --project P [--json]"
GET_USAGE = "yoke test-machine get --project P [--test-machine TEST_MACHINE] [--json]"
SETTINGS_REPLACE_USAGE = (
    "yoke test-machine settings-replace --project P "
    "[--test-machine TEST_MACHINE] --settings-file FILE "
    "(--base AS_READ_JSON | --new) [--json]"
)
VERIFY_USAGE = "yoke test-machine verify --project P [--test-machine TEST_MACHINE] [--json]"
RESET_USAGE = (
    "yoke test-machine reset --project P [--test-machine TEST_MACHINE] "
    "[--baseline fresh-host|shell-preconfigured] [--json]"
)
GOLDEN_CAPTURE_USAGE = (
    "yoke test-machine golden-capture --project P [--test-machine TEST_MACHINE] "
    "[--destination /abs/path] [--probes-file FILE] [--json]"
)
SCREENSHOT_USAGE = "yoke test-machine screenshot --project P [--test-machine TEST_MACHINE] [--json]"
BRIDGE_DIAGNOSE_USAGE = (
    "yoke test-machine bridge-diagnose --project P [--test-machine TEST_MACHINE] [--json]"
)


def _parser(prog: str, *, with_machine: bool = True) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=prog)
    parser.add_argument(
        "--project", required=True, help="Project that owns the test machine."
    )
    if with_machine:
        parser.add_argument(
            "--test-machine",
            metavar="TEST_MACHINE",
            help="Name of the test machine to use.",
        )
    add_session_arg(parser)
    add_json_arg(parser)
    return parser


def _dispatch(
    parsed: argparse.Namespace,
    function_id: str,
    payload: dict[str, Any],
    *,
    attest_local_secrets: bool = False,
) -> int:
    return dispatch_and_emit(
        function_id=function_id,
        target=TargetRef(kind="global"),
        payload={"project": parsed.project, **payload},
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
        response_recovery=(
            (
                lambda response, _actor: _attest_secret_presence(
                    response, parsed.project, function_id
                )
            )
            if attest_local_secrets
            else None
        ),
    )


def _attest_secret_presence(
    response: FunctionCallResponse,
    project: str,
    function_id: str,
) -> FunctionCallResponse:
    """Attach credential presence proven on this executing CLI machine."""
    if not response.success or not isinstance(response.result, dict):
        return response
    stored = set(list_machine_capability_secret_keys(project, TEST_MACHINE_CAPABILITY))

    def attest(detail: Any) -> Any:
        if not isinstance(detail, dict):
            return detail
        updated = dict(detail)
        capability_type = detail.get("capability_type")
        desktop_stored = (
            set(list_machine_capability_secret_keys(project, capability_type))
            if capability_type
            else set()
        )
        updated["secrets"] = [
            {
                **secret,
                "stored": secret.get("key")
                in (
                    desktop_stored
                    if secret.get("key") == DESKTOP_PASSWORD_KEY
                    else stored
                ),
            }
            for secret in detail.get("secrets") or []
            if isinstance(secret, dict)
        ]
        return updated

    result = dict(response.result)
    if function_id == "test_machine.list":
        test_machines = read_test_machine_field(
            result, function_id=function_id, field="test_machines"
        )
        result["test_machines"] = [attest(detail) for detail in test_machines]
    else:
        read_test_machine_field(result, function_id=function_id)
        result = attest(result)
    return response.model_copy(update={"result": result})


def test_machine_get(args: List[str]) -> int:
    parser = _parser("yoke test-machine get")
    parsed = parse_or_usage_error(parser, args, GET_USAGE)
    if parsed is None:
        return 2
    return _dispatch(
        parsed,
        "test_machine.get",
        {"test_machine": parsed.test_machine},
        attest_local_secrets=True,
    )


def test_machine_list(args: List[str]) -> int:
    parser = _parser("yoke test-machine list", with_machine=False)
    parsed = parse_or_usage_error(parser, args, LIST_USAGE)
    if parsed is None:
        return 2
    return _dispatch(
        parsed,
        "test_machine.list",
        {},
        attest_local_secrets=True,
    )


def test_machine_settings_replace(args: List[str]) -> int:
    parser = _parser("yoke test-machine settings-replace")
    parser.add_argument(
        "--settings-file",
        required=True,
        help="JSON file holding the new machine settings.",
    )
    base = parser.add_mutually_exclusive_group(required=True)
    base.add_argument(
        "--base",
        dest="base_settings",
        help="Settings JSON exactly as you read it; refuses if it changed since.",
    )
    base.add_argument(
        "--new",
        action="store_true",
        help="Create settings for a machine that has none yet.",
    )
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
            "test_machine": parsed.test_machine,
            "settings": settings,
            "base_settings": None if parsed.new else parsed.base_settings,
        },
    )


def test_machine_verify(args: List[str]) -> int:
    return run_host_operation(
        args,
        prog="yoke test-machine verify",
        usage=VERIFY_USAGE,
        operation="verify",
    )


def test_machine_reset(args: List[str]) -> int:
    return run_host_operation(
        args,
        prog="yoke test-machine reset",
        usage=RESET_USAGE,
        operation="reset",
        with_baseline=True,
    )


def test_machine_golden_capture(args: List[str]) -> int:
    return run_host_operation(
        args,
        prog="yoke test-machine golden-capture",
        usage=GOLDEN_CAPTURE_USAGE,
        operation="golden_capture",
        with_destination=True,
    )


def test_machine_screenshot(args: List[str]) -> int:
    return run_host_operation(
        args,
        prog="yoke test-machine screenshot",
        usage=SCREENSHOT_USAGE,
        operation="screenshot",
    )


def test_machine_bridge_diagnose(args: List[str]) -> int:
    return run_host_operation(
        args,
        prog="yoke test-machine bridge-diagnose",
        usage=BRIDGE_DIAGNOSE_USAGE,
        operation="bridge_diagnose",
    )


USAGE_BY_FUNCTION_ID = {
    "test_machine.screenshot": SCREENSHOT_USAGE,
    "test_machine.list": LIST_USAGE,
    "test_machine.get": GET_USAGE,
    "test_machine.settings_replace": SETTINGS_REPLACE_USAGE,
    "test_machine.verify": VERIFY_USAGE,
    "test_machine.reset": RESET_USAGE,
    "test_machine.golden_capture": GOLDEN_CAPTURE_USAGE,
    "test_machine.bridge_diagnose": BRIDGE_DIAGNOSE_USAGE,
}


__all__ = [
    "BRIDGE_DIAGNOSE_USAGE",
    "GET_USAGE",
    "GOLDEN_CAPTURE_USAGE",
    "LIST_USAGE",
    "RESET_USAGE",
    "SCREENSHOT_USAGE",
    "SETTINGS_REPLACE_USAGE",
    "USAGE_BY_FUNCTION_ID",
    "VERIFY_USAGE",
    "test_machine_bridge_diagnose",
    "test_machine_get",
    "test_machine_golden_capture",
    "test_machine_list",
    "test_machine_reset",
    "test_machine_screenshot",
    "test_machine_settings_replace",
    "test_machine_verify",
]
