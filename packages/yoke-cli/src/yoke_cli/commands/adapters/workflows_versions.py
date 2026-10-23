"""CLI adapters for immutable workflow version controls."""

from __future__ import annotations
from yoke_cli.transport.human_values import write_human

import argparse
from typing import List

from yoke_cli.commands._helpers import (
    add_json_arg,
    add_session_arg,
    dispatch_and_emit,
    parse_or_usage_error,
    usage_error,
)
from yoke_contracts.api.function_call import TargetRef


WORKFLOWS_CURRENT_SET_USAGE = (
    "yoke workflows current set WORKFLOW VERSION "
    "[--expected-current-version N] [--session-id S] [--json]"
)
WORKFLOWS_VERSION_GET_USAGE = (
    "yoke workflows version get WORKFLOW VERSION [--session-id S] [--json]"
)
WORKFLOWS_VERSION_LIST_USAGE = (
    "yoke workflows version list [WORKFLOW] [--session-id S] [--json]"
)
WORKFLOWS_POLICY_DEFAULTS_PUBLISH_USAGE = (
    "yoke workflows policy-defaults publish WORKFLOW "
    "(--file-budget on|off | --path-claims on|off | --path-survey on|off) "
    "--expected-current-version N [--session-id S] [--json]"
)


def workflows_current_set(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke workflows current set",
        usage=WORKFLOWS_CURRENT_SET_USAGE,
    )
    parser.add_argument("workflow", help="Workflow id.")
    parser.add_argument("version", type=int, help="Version to make current.")
    parser.add_argument(
        "--expected-current-version",
        type=int,
        default=None,
        help="Current version you read; a different one refuses the change.",
    )
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, WORKFLOWS_CURRENT_SET_USAGE)
    if parsed is None:
        return 2

    def _human_writer(response, stdout, stderr) -> None:
        write_human(response.result or {}, stdout)

    payload = {"workflow_id": parsed.workflow, "version": parsed.version}
    if parsed.expected_current_version is not None:
        payload["expected_current_version"] = parsed.expected_current_version
    return dispatch_and_emit(
        function_id="workflows.current.set",
        target=TargetRef(kind="global"),
        payload=payload,
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
        human_writer=_human_writer,
    )


def _one_argument_version_get(args: List[str]) -> str | None:
    positionals = [arg for arg in args if not str(arg).startswith("-")]
    if len(positionals) != 1:
        return None
    return (
        "workflows_version_arguments: yoke workflows version get needs "
        "WORKFLOW and VERSION. "
        f"Got only {positionals[0]!r}. "
        "WORKFLOW is the workflow slug (workflow_id). "
        "VERSION is the version number from "
        "`yoke workflows item get PREFIX-N` result.workflow_version, "
        "not workflow_version_id."
    )


def workflows_version_get(args: List[str]) -> int:
    shape = _one_argument_version_get(args)
    if shape is not None:
        return usage_error(shape)
    parser = argparse.ArgumentParser(
        prog="yoke workflows version get",
        usage=WORKFLOWS_VERSION_GET_USAGE,
    )
    parser.add_argument("workflow", help="Workflow id.")
    parser.add_argument("version", type=int, help="Version to read.")
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, WORKFLOWS_VERSION_GET_USAGE)
    if parsed is None:
        return 2

    def _human_writer(response, stdout, stderr) -> None:
        write_human(response.result or {}, stdout)

    return dispatch_and_emit(
        function_id="workflows.version.get",
        target=TargetRef(kind="global"),
        payload={
            "workflow_id": parsed.workflow,
            "version": parsed.version,
        },
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
        human_writer=_human_writer,
    )


def workflows_version_list(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke workflows version list",
        usage=WORKFLOWS_VERSION_LIST_USAGE,
    )
    parser.add_argument(
        "workflow", nargs="?", default=None, help="Workflow id; default: all workflows."
    )
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, WORKFLOWS_VERSION_LIST_USAGE)
    if parsed is None:
        return 2

    def _human_writer(response, stdout, stderr) -> None:
        write_human(response.result or {}, stdout)

    payload = {}
    if parsed.workflow:
        payload["workflow_id"] = parsed.workflow
    return dispatch_and_emit(
        function_id="workflows.version.list",
        target=TargetRef(kind="global"),
        payload=payload,
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
        human_writer=_human_writer,
    )


def workflows_policy_defaults_publish(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke workflows policy-defaults publish",
        usage=WORKFLOWS_POLICY_DEFAULTS_PUBLISH_USAGE,
    )
    parser.add_argument("workflow", help="Workflow id.")
    policy = parser.add_mutually_exclusive_group(required=True)
    policy.add_argument(
        "--file-budget", choices=("on", "off"), help="Turn the file budget on or off."
    )
    policy.add_argument(
        "--path-claims", choices=("on", "off"), help="Turn path claims on or off."
    )
    policy.add_argument(
        "--path-survey", choices=("on", "off"), help="Turn the path survey on or off."
    )
    parser.add_argument(
        "--expected-current-version",
        type=int,
        required=True,
        help="Current version you read; a different one refuses the change.",
    )
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, WORKFLOWS_POLICY_DEFAULTS_PUBLISH_USAGE)
    if parsed is None:
        return 2

    def _human_writer(response, stdout, stderr) -> None:
        write_human(response.result or {}, stdout)

    if parsed.file_budget is not None:
        policy_payload = {"file_budget_default": parsed.file_budget == "on"}
    elif parsed.path_claims is not None:
        policy_payload = {"path_claims_default": parsed.path_claims == "on"}
    else:
        policy_payload = {"path_survey_default": parsed.path_survey == "on"}
    return dispatch_and_emit(
        function_id="workflows.policy_defaults.publish",
        target=TargetRef(kind="global"),
        payload={
            "workflow_id": parsed.workflow,
            "expected_current_version": parsed.expected_current_version,
            **policy_payload,
        },
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
        human_writer=_human_writer,
    )


__all__ = [
    "WORKFLOWS_CURRENT_SET_USAGE",
    "WORKFLOWS_POLICY_DEFAULTS_PUBLISH_USAGE",
    "WORKFLOWS_VERSION_GET_USAGE",
    "WORKFLOWS_VERSION_LIST_USAGE",
    "workflows_current_set",
    "workflows_policy_defaults_publish",
    "workflows_version_get",
    "workflows_version_list",
]
