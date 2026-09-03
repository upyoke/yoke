"""Thin CLI adapters for bounded workflow-mechanics editors."""

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


GET_USAGE = "yoke workflows mechanics get [--json]"
TESTING_SET_USAGE = (
    "yoke workflows testing-default set --project P --workflow W "
    "--plan-id N [--apply-to-all] [--json]"
)
DELIVERY_SET_USAGE = (
    "yoke workflows delivery-default set --project P --workflow W "
    "--flow F [--apply-to-all] [--json]"
)
APPROVAL_PUBLISH_USAGE = (
    "yoke workflows approval-defaults publish --workflow W "
    "--expected-current-version N --defaults-file FILE [--json]"
)


def _parser(prog: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=prog)
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
        payload=payload,
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
    )


def workflows_mechanics_get(args: List[str]) -> int:
    parser = _parser("yoke workflows mechanics get")
    parsed = parse_or_usage_error(parser, args, GET_USAGE)
    if parsed is None:
        return 2
    return _dispatch(parsed, "workflows.mechanics.get", {})


def _project_default_parser(
    prog: str,
    *,
    value_flag: str,
    value_type: type = str,
) -> argparse.ArgumentParser:
    parser = _parser(prog)
    parser.add_argument("--project", required=True)
    parser.add_argument("--workflow", required=True)
    parser.add_argument(value_flag, required=True, type=value_type)
    parser.add_argument("--apply-to-all", action="store_true")
    return parser


def workflows_testing_default_set(args: List[str]) -> int:
    parser = _project_default_parser(
        "yoke workflows testing-default set",
        value_flag="--plan-id",
        value_type=int,
    )
    parsed = parse_or_usage_error(parser, args, TESTING_SET_USAGE)
    if parsed is None:
        return 2
    return _dispatch(parsed, "workflows.testing_default.set", {
        "project": parsed.project,
        "workflow_id": parsed.workflow,
        "plan_id": parsed.plan_id,
        "apply_to_all": parsed.apply_to_all,
    })


def workflows_delivery_default_set(args: List[str]) -> int:
    parser = _project_default_parser(
        "yoke workflows delivery-default set",
        value_flag="--flow",
    )
    parsed = parse_or_usage_error(parser, args, DELIVERY_SET_USAGE)
    if parsed is None:
        return 2
    return _dispatch(parsed, "workflows.delivery_default.set", {
        "project": parsed.project,
        "workflow_id": parsed.workflow,
        "flow_id": parsed.flow,
        "apply_to_all": parsed.apply_to_all,
    })


def workflows_approval_defaults_publish(args: List[str]) -> int:
    parser = _parser("yoke workflows approval-defaults publish")
    parser.add_argument("--workflow", required=True)
    parser.add_argument("--expected-current-version", required=True, type=int)
    parser.add_argument(
        "--defaults-file",
        required=True,
        help=(
            "JSON file mapping each gated transition id to its approval "
            'policy: {"roles": [...], "actors": [...], "mode": '
            '"any"|"all"}. "mode" defaults to "any", where the first '
            'approval from anyone listed settles the gate; "all" needs '
            "one decision per checked role or named person, and any "
            "rejection by a listed party rejects. A transition with "
            "nothing checked has no approval gate."
        ),
    )
    parsed = parse_or_usage_error(parser, args, APPROVAL_PUBLISH_USAGE)
    if parsed is None:
        return 2
    try:
        defaults = json.loads(
            Path(parsed.defaults_file).read_text(encoding="utf-8")
        )
    except (OSError, ValueError) as exc:
        return usage_error(f"defaults file must be readable JSON: {exc}")
    if not isinstance(defaults, dict):
        return usage_error("defaults file root must be an object")
    return _dispatch(parsed, "workflows.approval_defaults.publish", {
        "workflow_id": parsed.workflow,
        "expected_current_version": parsed.expected_current_version,
        "approval_defaults": defaults,
    })


USAGE_BY_FUNCTION_ID = {
    "workflows.mechanics.get": GET_USAGE,
    "workflows.testing_default.set": TESTING_SET_USAGE,
    "workflows.delivery_default.set": DELIVERY_SET_USAGE,
    "workflows.approval_defaults.publish": APPROVAL_PUBLISH_USAGE,
}


__all__ = [
    "APPROVAL_PUBLISH_USAGE",
    "DELIVERY_SET_USAGE",
    "GET_USAGE",
    "TESTING_SET_USAGE",
    "USAGE_BY_FUNCTION_ID",
    "workflows_approval_defaults_publish",
    "workflows_delivery_default_set",
    "workflows_mechanics_get",
    "workflows_testing_default_set",
]
