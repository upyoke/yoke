"""CLI adapters for immutable workflow version controls."""

from __future__ import annotations

import argparse
from typing import List

from yoke_cli.commands._helpers import (
    add_json_arg,
    add_session_arg,
    dispatch_and_emit,
    parse_or_usage_error,
)
from yoke_contracts.api.function_call import TargetRef


WORKFLOWS_CURRENT_SET_USAGE = (
    "yoke workflows current set WORKFLOW VERSION "
    "[--expected-current-version N] [--session-id S] [--json]"
)
WORKFLOWS_VERSION_GET_USAGE = (
    "yoke workflows version get WORKFLOW VERSION [--session-id S] [--json]"
)
WORKFLOWS_POLICY_DEFAULTS_PUBLISH_USAGE = (
    "yoke workflows policy-defaults publish WORKFLOW --path-claims on|off "
    "--expected-current-version N [--session-id S] [--json]"
)


def workflows_current_set(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke workflows current set",
        description=WORKFLOWS_CURRENT_SET_USAGE,
    )
    parser.add_argument("workflow")
    parser.add_argument("version", type=int)
    parser.add_argument("--expected-current-version", type=int, default=None)
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(
        parser, args, WORKFLOWS_CURRENT_SET_USAGE
    )
    if parsed is None:
        return 2

    def _human_writer(response, stdout, stderr) -> None:
        result = response.result or {}
        print(
            f"workflow-current|{result.get('workflow_id') or ''}|"
            f"{result.get('version') or ''}|"
            f"{result.get('version_id') or ''}",
            file=stdout,
        )

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


def workflows_version_get(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke workflows version get",
        description=WORKFLOWS_VERSION_GET_USAGE,
    )
    parser.add_argument("workflow")
    parser.add_argument("version", type=int)
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, WORKFLOWS_VERSION_GET_USAGE)
    if parsed is None:
        return 2

    def _human_writer(response, stdout, stderr) -> None:
        result = response.result or {}
        print(
            f"workflow-version|{result.get('workflow_id') or ''}|"
            f"{result.get('version') or ''}|"
            f"{str(bool(result.get('current'))).lower()}|"
            f"{result.get('definition_digest') or ''}",
            file=stdout,
        )

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


def workflows_policy_defaults_publish(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke workflows policy-defaults publish",
        description=WORKFLOWS_POLICY_DEFAULTS_PUBLISH_USAGE,
    )
    parser.add_argument("workflow")
    parser.add_argument("--path-claims", choices=("on", "off"), required=True)
    parser.add_argument("--expected-current-version", type=int, required=True)
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(
        parser, args, WORKFLOWS_POLICY_DEFAULTS_PUBLISH_USAGE
    )
    if parsed is None:
        return 2

    def _human_writer(response, stdout, stderr) -> None:
        result = response.result or {}
        path_claims = "on" if result.get("path_claims_default") else "off"
        print(
            f"workflow-defaults-published|"
            f"{result.get('workflow_id') or ''}|"
            f"{result.get('version') or ''}|path-claims={path_claims}",
            file=stdout,
        )

    return dispatch_and_emit(
        function_id="workflows.policy_defaults.publish",
        target=TargetRef(kind="global"),
        payload={
            "workflow_id": parsed.workflow,
            "expected_current_version": parsed.expected_current_version,
            "path_claims_default": parsed.path_claims == "on",
        },
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
        human_writer=_human_writer,
    )


__all__ = [
    "WORKFLOWS_CURRENT_SET_USAGE",
    "WORKFLOWS_POLICY_DEFAULTS_PUBLISH_USAGE",
    "WORKFLOWS_VERSION_GET_USAGE",
    "workflows_current_set",
    "workflows_policy_defaults_publish",
    "workflows_version_get",
]
