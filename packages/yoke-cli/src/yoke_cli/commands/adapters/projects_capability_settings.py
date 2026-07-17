"""HTTPS-safe ``yoke projects capability-settings ...`` adapters."""

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


PROJECTS_CAPABILITY_SETTINGS_GET_USAGE = (
    "yoke projects capability-settings get --project NAME --cap-type TYPE "
    "[--session-id S] [--json]"
)
PROJECTS_CAPABILITY_SETTINGS_SET_USAGE = (
    "yoke projects capability-settings set --project NAME --cap-type TYPE "
    "--settings-json JSON (--base AS_READ_JSON | --new) "
    "[--session-id S] [--json]"
)
PROJECTS_CAPABILITY_SETTINGS_MERGE_USAGE = (
    "yoke projects capability-settings merge --project NAME --cap-type TYPE "
    "--set KEY.PATH=VALUE [--set ...] [--session-id S] [--json]"
)


def projects_capability_settings_get(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke projects capability-settings get",
        description=(
            "Read one non-sensitive project capability settings document. "
            "The exact output is the --base token for a CAS set."
        ),
    )
    _add_identity_args(parser)
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, PROJECTS_CAPABILITY_SETTINGS_GET_USAGE)
    if parsed is None:
        return 2
    return _dispatch(
        "projects.capability_settings.get",
        parsed,
        {"project": parsed.project, "cap_type": parsed.cap_type},
    )


def projects_capability_settings_set(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke projects capability-settings set",
        description=(
            "Create or CAS-replace one non-sensitive settings document. "
            "Typed capabilities are validated and canonicalized server-side."
        ),
    )
    _add_identity_args(parser)
    parser.add_argument("--settings-json", required=True)
    choice = parser.add_mutually_exclusive_group(required=True)
    choice.add_argument("--base", dest="base_settings_json")
    choice.add_argument("--new", dest="create", action="store_true")
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, PROJECTS_CAPABILITY_SETTINGS_SET_USAGE)
    if parsed is None:
        return 2
    payload: Dict[str, Any] = {
        "project": parsed.project,
        "cap_type": parsed.cap_type,
        "settings_json": parsed.settings_json,
        "create": parsed.create,
    }
    if parsed.base_settings_json is not None:
        payload["base_settings_json"] = parsed.base_settings_json
    return _dispatch("projects.capability_settings.set", parsed, payload)


def projects_capability_settings_merge(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke projects capability-settings merge",
        description=(
            "Merge key paths through a server-side read-merge-CAS loop. "
            "Concurrent independent updates compose."
        ),
    )
    _add_identity_args(parser)
    parser.add_argument(
        "--set",
        dest="assignments",
        action="append",
        required=True,
        metavar="KEY.PATH=VALUE",
    )
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(
        parser, args, PROJECTS_CAPABILITY_SETTINGS_MERGE_USAGE
    )
    if parsed is None:
        return 2
    try:
        assignments = _parse_assignments(parsed.assignments)
    except ValueError as exc:
        return usage_error(str(exc))
    return _dispatch(
        "projects.capability_settings.merge",
        parsed,
        {
            "project": parsed.project,
            "cap_type": parsed.cap_type,
            "assignments": assignments,
        },
    )


def _add_identity_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--project", required=True)
    parser.add_argument("--cap-type", dest="cap_type", required=True)


def _dispatch(
    function_id: str, parsed: argparse.Namespace, payload: Dict[str, Any]
) -> int:
    def _human_writer(response, stdout, stderr) -> None:
        del stderr
        if not response.success:
            return None
        result = response.result or {}
        if result.get("changed_paths") is not None:
            stdout.write(",".join(result.get("changed_paths") or []) + "\n")
            return None
        settings_json = str(result.get("settings_json") or "")
        stdout.write(settings_json)
        if not settings_json.endswith("\n"):
            stdout.write("\n")
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
    "PROJECTS_CAPABILITY_SETTINGS_GET_USAGE",
    "PROJECTS_CAPABILITY_SETTINGS_MERGE_USAGE",
    "PROJECTS_CAPABILITY_SETTINGS_SET_USAGE",
    "projects_capability_settings_get",
    "projects_capability_settings_merge",
    "projects_capability_settings_set",
]
