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
        settings = json.loads(
            Path(parsed.settings_file).read_text(encoding="utf-8")
        )
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
    return _dispatch(parsed, "test_machine.verify", {})


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
