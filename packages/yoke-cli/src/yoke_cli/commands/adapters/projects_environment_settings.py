"""HTTPS-safe ``yoke projects environment-settings ...`` adapters."""

from __future__ import annotations

import argparse
import json
from typing import Any, Dict, List

from yoke_cli.commands._helpers import (
    add_json_arg,
    add_session_arg,
    dispatch_and_emit,
    parse_or_usage_error,
    usage_error,
)
from yoke_contracts.api.function_call import TargetRef


GET_USAGE = (
    "yoke projects environment-settings get --project NAME "
    "--environment-id ID --path KEY.PATH [--path ...] "
    "[--session-id S] [--json]"
)
MERGE_USAGE = (
    "yoke projects environment-settings merge --project NAME "
    "--environment-id ID --set KEY.PATH=VALUE [--set ...] "
    "[--session-id S] [--json]"
)


def projects_environment_settings_get(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke projects environment-settings get"
    )
    _add_identity_args(parser)
    parser.add_argument("--path", dest="paths", action="append", required=True)
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, GET_USAGE)
    if parsed is None:
        return 2
    return _dispatch(
        "projects.environment_settings.get",
        parsed,
        {
            "project": parsed.project,
            "environment_id": parsed.environment_id,
            "paths": parsed.paths,
        },
    )


def projects_environment_settings_merge(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke projects environment-settings merge"
    )
    _add_identity_args(parser)
    parser.add_argument(
        "--set", dest="assignments", action="append", required=True
    )
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, MERGE_USAGE)
    if parsed is None:
        return 2
    try:
        assignments = _parse_assignments(parsed.assignments)
    except ValueError as exc:
        return usage_error(str(exc))
    return _dispatch(
        "projects.environment_settings.merge",
        parsed,
        {
            "project": parsed.project,
            "environment_id": parsed.environment_id,
            "assignments": assignments,
        },
    )


def _add_identity_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--project", required=True)
    parser.add_argument("--environment-id", dest="environment_id", required=True)


def _dispatch(
    function_id: str, parsed: argparse.Namespace, payload: Dict[str, Any]
) -> int:
    def _human_writer(response, stdout, stderr) -> None:
        del stderr
        if not response.success:
            return None
        result = response.result or {}
        if function_id == "projects.environment_settings.get":
            for path, value in (result.get("values") or {}).items():
                stdout.write(f"{path}={json.dumps(value, sort_keys=True)}\n")
        else:
            paths = ",".join(result.get("changed_paths") or [])
            stdout.write(f"{result.get('environment_id', '')}|{paths}\n")
        return None

    return dispatch_and_emit(
        function_id=function_id,
        target=TargetRef(kind="global"),
        payload=payload,
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
        human_writer=_human_writer,
    )


def _parse_assignments(raw_assignments: List[str]) -> Dict[str, Any]:
    parsed: Dict[str, Any] = {}
    for assignment in raw_assignments:
        key, separator, raw_value = assignment.partition("=")
        key = key.strip()
        if not separator or not key:
            raise ValueError("--set requires KEY.PATH=VALUE")
        try:
            value: Any = json.loads(raw_value)
        except json.JSONDecodeError:
            value = raw_value
        parsed[key] = value
    return parsed


__all__ = [
    "GET_USAGE",
    "MERGE_USAGE",
    "projects_environment_settings_get",
    "projects_environment_settings_merge",
]
