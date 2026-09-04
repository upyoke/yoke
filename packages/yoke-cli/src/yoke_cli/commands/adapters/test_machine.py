"""CLI adapters for the composite test-machine capability."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, List

from yoke_contracts.api.function_call import TargetRef
from yoke_cli.commands._helpers import (
    add_json_arg,
    add_session_arg,
    dispatch_and_emit,
    parse_or_usage_error,
    usage_error,
)
from yoke_cli.commands.adapters.test_machine_operation import run_host_operation


LIST_USAGE = "yoke test-machine list --project P [--json]"
GET_USAGE = "yoke test-machine get --project P [--machine NAME] [--json]"
SETTINGS_REPLACE_USAGE = (
    "yoke test-machine settings-replace --project P "
    "[--machine NAME] --settings-file FILE "
    "(--base AS_READ_JSON | --new) [--json]"
)
VERIFY_USAGE = "yoke test-machine verify --project P [--machine NAME] [--json]"
RESET_USAGE = (
    "yoke test-machine reset --project P [--machine NAME] "
    "[--baseline fresh-host|shell-preconfigured] [--json]"
)
GOLDEN_CAPTURE_USAGE = (
    "yoke test-machine golden-capture --project P [--machine NAME] "
    "[--destination /abs/path] [--probes-file FILE] [--json]"
)
BRIDGE_DIAGNOSE_USAGE = (
    "yoke test-machine bridge-diagnose --project P [--machine NAME] [--json]"
)


def _parser(prog: str, *, with_machine: bool = True) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=prog)
    parser.add_argument("--project", required=True)
    if with_machine:
        parser.add_argument("--machine")
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
    return _dispatch(parsed, "test_machine.get", {"machine": parsed.machine})


def test_machine_list(args: List[str]) -> int:
    parser = _parser("yoke test-machine list", with_machine=False)
    parsed = parse_or_usage_error(parser, args, LIST_USAGE)
    if parsed is None:
        return 2
    return _dispatch(parsed, "test_machine.list", {})


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
            "machine": parsed.machine,
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


def test_machine_bridge_diagnose(args: List[str]) -> int:
    return run_host_operation(
        args,
        prog="yoke test-machine bridge-diagnose",
        usage=BRIDGE_DIAGNOSE_USAGE,
        operation="bridge_diagnose",
    )


USAGE_BY_FUNCTION_ID = {
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
    "SETTINGS_REPLACE_USAGE",
    "USAGE_BY_FUNCTION_ID",
    "VERIFY_USAGE",
    "test_machine_bridge_diagnose",
    "test_machine_get",
    "test_machine_golden_capture",
    "test_machine_list",
    "test_machine_reset",
    "test_machine_settings_replace",
    "test_machine_verify",
]
